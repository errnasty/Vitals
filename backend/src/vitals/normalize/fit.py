"""The FIT file: what the watch recorded second by second.

Everything else in this app comes from Garmin's *summary* of an activity. This is the
recording itself — a heart rate, a position and a power reading for every second the
watch was running — and it is the only layer that can answer questions the summary has
already thrown away: whether your heart rate drifted while your pace held, what the
power actually looked like rather than its average, where you went.

**No per-second row ever reaches Postgres.** An hour's run is 3,600 samples across
eight channels, and a few years of training would be tens of millions of rows earning
their keep about twice a year. So the streams are decoded here, in memory, reduced to
the handful of facts that cannot be recovered from a mean, and dropped. The file
itself is kept verbatim in binary bronze, so a better reduction later is a recompute
rather than a re-download — which matters more here than anywhere else, because Garmin
serves FIT files through the same unofficial API that could vanish tomorrow.

**What is computed here needs no profile.** Normalized power, variability, decoupling
and elevation are properties of the recording alone. Anything that needs to know *your*
maximum heart rate — time in zones, most obviously — belongs where the response
profile lives, not here, because a zone boundary guessed from 220-minus-age is a number
that looks precise and is not.
"""

from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

import fitdecode

# Garmin stores latitude and longitude as semicircles: a signed 32-bit integer over
# the full circle. This is the documented conversion, not an approximation.
SEMICIRCLE_DEGREES = 180.0 / (2**31)

# Normalized power's rolling window, from Coggan's original definition. Thirty
# seconds is not a tuning parameter — it stands for how long the body takes to
# respond to a change in effort, and changing it makes the number incomparable with
# every other tool that reports one.
NP_WINDOW_S = 30
NP_EXPONENT = 4

# A climb has to clear this before it counts, or GPS altitude noise on a flat road
# accumulates into hundreds of metres of imaginary ascent over an hour.
ASCENT_THRESHOLD_M = 1.0

# Below this there is no second half to compare the first half against.
MIN_DECOUPLING_SAMPLES = 120

# The route is drawn, not tiled, into the design system's 380x300 box.
ROUTE_W, ROUTE_H = 380.0, 300.0
ROUTE_PAD = 12.0
# Enough points that a switchback still reads as a switchback, few enough that the
# path string stays a few kilobytes rather than a few hundred.
ROUTE_POINTS = 240


class UnreadableFit(ValueError):
    """The bytes are not a FIT file, or not one this can make sense of."""


@dataclass(slots=True)
class Streams:
    """One activity's recording, channel by channel.

    Lists rather than a list of records, because every calculation below walks one
    channel at a time. A missing reading is `None` and stays `None` — an indoor ride
    has no position and a heart-rate strap drops out, and filling either in would
    invent the thing being measured.
    """

    timestamps: list[datetime] = field(default_factory=list)
    heart_rate: list[float | None] = field(default_factory=list)
    power: list[float | None] = field(default_factory=list)
    cadence: list[float | None] = field(default_factory=list)
    speed: list[float | None] = field(default_factory=list)
    altitude: list[float | None] = field(default_factory=list)
    distance: list[float | None] = field(default_factory=list)
    latitude: list[float | None] = field(default_factory=list)
    longitude: list[float | None] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.timestamps)


@dataclass(frozen=True, slots=True)
class FitSummary:
    """What the recording knew that the summary did not."""

    samples: int
    # Seconds between readings. Garmin's "smart recording" is not 1Hz, and a
    # rolling window measured in samples would mean different things on different
    # devices.
    sample_interval_s: float | None
    normalized_power: float | None
    variability_index: float | None
    # Friel's aerobic decoupling, as a percentage. Positive means the second half
    # cost more heartbeats for the same speed.
    decoupling_pct: float | None
    hr_drift_bpm: float | None
    ascent_m: float | None
    descent_m: float | None
    moving_time_s: float | None
    # An SVG path in the design system's 380x300 box. Projected here because the
    # rule everywhere else holds here too: components take finished values.
    route_path: str | None
    route_points: int


def unzip(blob: bytes) -> bytes:
    """Garmin serves the original recording as a zip holding one `.fit` file."""
    if blob[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".fit")]
            if not names:
                raise UnreadableFit("the archive holds no .fit file")
            return archive.read(names[0])
    return blob


def _value(message: fitdecode.FitDataMessage, *names: str) -> float | None:
    """The first of several field names that carries a usable number.

    The aliases are not defensive padding. A device that records altitude with a
    barometer writes `enhanced_altitude`; one without writes `altitude`, and the same
    split exists for speed. Reading only the first would silently lose every reading
    from half the devices Garmin sells.
    """
    for name in names:
        try:
            raw = message.get_value(name)
        except KeyError:
            continue
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return float(raw)
    return None


def decode(blob: bytes) -> Streams:
    """Walk the file once, keeping only the `record` messages."""
    streams = Streams()
    try:
        with fitdecode.FitReader(io.BytesIO(unzip(blob))) as reader:
            for frame in reader:
                if not isinstance(frame, fitdecode.FitDataMessage) or frame.name != "record":
                    continue
                stamp = frame.get_value("timestamp") if frame.has_field("timestamp") else None
                if not isinstance(stamp, datetime):
                    continue

                streams.timestamps.append(stamp)
                streams.heart_rate.append(_value(frame, "heart_rate"))
                streams.power.append(_value(frame, "power"))
                streams.cadence.append(_value(frame, "cadence"))
                streams.speed.append(_value(frame, "enhanced_speed", "speed"))
                streams.altitude.append(_value(frame, "enhanced_altitude", "altitude"))
                streams.distance.append(_value(frame, "distance"))

                lat = _value(frame, "position_lat")
                lon = _value(frame, "position_long")
                streams.latitude.append(None if lat is None else lat * SEMICIRCLE_DEGREES)
                streams.longitude.append(None if lon is None else lon * SEMICIRCLE_DEGREES)
    except UnreadableFit:
        raise
    except Exception as exc:  # noqa: BLE001 - any malformed file, reported as one thing
        raise UnreadableFit(f"{type(exc).__name__}: {exc}") from exc

    return streams


def _present(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None]


def _interval(stamps: list[datetime]) -> float | None:
    """The median gap between readings.

    Median rather than mean because a pause mid-ride is one enormous gap, and a mean
    that includes it would report a 1Hz recording as one sample every forty seconds.
    """
    if len(stamps) < 2:
        return None
    gaps = sorted(
        (stamps[i + 1] - stamps[i]).total_seconds()
        for i in range(len(stamps) - 1)
        if (stamps[i + 1] - stamps[i]).total_seconds() > 0
    )
    if not gaps:
        return None
    return gaps[len(gaps) // 2]


def normalized_power(power: list[float | None], *, interval_s: float) -> float | None:
    """Coggan's normalized power: the effort a steady ride would have had to be.

    Thirty seconds of rolling average, raised to the fourth, averaged, rooted. The
    fourth power is the whole point — it is what makes a ride of surges cost more
    than its mean suggests, which is exactly the thing an average hides.

    Gaps are dropped rather than zero-filled. A dropout is not a coast, and treating
    it as one would drag the number down precisely when the recording is worst.
    """
    values = _present(power)
    window = max(1, round(NP_WINDOW_S / interval_s)) if interval_s > 0 else NP_WINDOW_S
    if len(values) < window:
        return None

    rolling: list[float] = []
    total = sum(values[:window])
    rolling.append(total / window)
    for i in range(window, len(values)):
        total += values[i] - values[i - window]
        rolling.append(total / window)

    mean_fourth = sum(v**NP_EXPONENT for v in rolling) / len(rolling)
    return float(mean_fourth ** (1 / NP_EXPONENT))


def decoupling(
    heart_rate: list[float | None], speed: list[float | None]
) -> tuple[float | None, float | None]:
    """Aerobic decoupling, and the raw heart-rate drift behind it.

    Split the effort in half and compare speed-per-heartbeat in each. If the second
    half needed more heartbeats for the same speed, the aerobic system was giving
    way — which is the single most useful thing a long steady effort can tell you,
    and it is invisible in any average.

    Only samples where *both* channels read are used, and the halves are taken over
    those. Comparing a first half full of heart rate with a second half that lost the
    strap would produce a large, confident, meaningless number.
    """
    paired = [
        (hr, sp)
        for hr, sp in zip(heart_rate, speed, strict=False)
        if hr is not None and sp is not None and hr > 0 and sp > 0
    ]
    if len(paired) < MIN_DECOUPLING_SAMPLES:
        return None, None

    middle = len(paired) // 2
    first, second = paired[:middle], paired[middle:]

    def ratio(half: list[tuple[float, float]]) -> float | None:
        hr_mean = sum(h for h, _ in half) / len(half)
        sp_mean = sum(s for _, s in half) / len(half)
        return None if hr_mean <= 0 else sp_mean / hr_mean

    first_ratio, second_ratio = ratio(first), ratio(second)
    drift = (sum(h for h, _ in second) / len(second)) - (sum(h for h, _ in first) / len(first))

    if first_ratio is None or second_ratio is None or first_ratio == 0:
        return None, drift
    # Positive means efficiency fell: the same speed cost more heartbeats later on.
    return float((first_ratio - second_ratio) / first_ratio * 100.0), float(drift)


def climb(altitude: list[float | None]) -> tuple[float | None, float | None]:
    """Metres up and metres down, with a threshold under the noise floor.

    A barometric altimeter wanders by a metre or two while standing still. Summing
    every positive difference turns that wander into ascent, and an hour on a flat
    road comes back as a mountain stage. Only a move that clears the threshold from
    the last confirmed point counts.
    """
    values = _present(altitude)
    if len(values) < 2:
        return None, None

    up = down = 0.0
    anchor = values[0]
    for value in values[1:]:
        change = value - anchor
        if change >= ASCENT_THRESHOLD_M:
            up += change
            anchor = value
        elif change <= -ASCENT_THRESHOLD_M:
            down += -change
            anchor = value
    return up, down


def moving_time(speed: list[float | None], *, interval_s: float) -> float | None:
    """Seconds actually moving, from the recording rather than the watch's opinion."""
    values = _present(speed)
    if not values or interval_s <= 0:
        return None
    return float(sum(1 for v in values if v > 0.0) * interval_s)


def _downsample(points: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    """Evenly spaced points, always keeping the first and the last.

    Evenly spaced rather than Douglas-Peucker: this feeds a 380-pixel drawing, where
    the difference between the two is invisible, and an even stride cannot drop the
    finish line.
    """
    if len(points) <= limit:
        return points
    stride = (len(points) - 1) / (limit - 1)
    picked = [points[round(i * stride)] for i in range(limit - 1)]
    picked.append(points[-1])
    return picked


def route(latitude: list[float | None], longitude: list[float | None]) -> tuple[str | None, int]:
    """The track, as an SVG path in the design system's 380x300 box.

    Projected here rather than in the browser, for the same reason every other number
    is computed here: a component that projects is a component that can disagree with
    the data it was given.

    Longitude is scaled by cos(latitude) before fitting. Without it a route at London's
    latitude comes out stretched about 60% too wide east-to-west — a run around a
    square park would draw as a rectangle, which is not a rounding error but a wrong
    picture.
    """
    points = [
        (lat, lon)
        for lat, lon in zip(latitude, longitude, strict=False)
        if lat is not None and lon is not None and (lat, lon) != (0.0, 0.0)
    ]
    if len(points) < 2:
        return None, 0

    points = _downsample(points, ROUTE_POINTS)

    lats = [lat for lat, _ in points]
    lons = [lon for _, lon in points]
    mid_lat = (min(lats) + max(lats)) / 2
    # cos at the route's own latitude, so the aspect ratio is right where it is.
    squeeze = max(math.cos(math.radians(mid_lat)), 1e-6)

    xs = [lon * squeeze for lon in lons]
    ys = lats
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_x <= 0 and span_y <= 0:
        return None, 0

    # One scale for both axes, so the shape is not distorted to fill the box.
    scale = min(
        (ROUTE_W - 2 * ROUTE_PAD) / span_x if span_x > 0 else float("inf"),
        (ROUTE_H - 2 * ROUTE_PAD) / span_y if span_y > 0 else float("inf"),
    )
    offset_x = (ROUTE_W - span_x * scale) / 2
    offset_y = (ROUTE_H - span_y * scale) / 2

    commands: list[str] = []
    for index, (x, y) in enumerate(zip(xs, ys, strict=True)):
        px = offset_x + (x - min(xs)) * scale
        # SVG's y axis points down; north should point up.
        py = ROUTE_H - offset_y - (y - min(ys)) * scale
        commands.append(f"{'M' if index == 0 else 'L'}{px:.1f} {py:.1f}")

    return " ".join(commands), len(points)


def summarise(streams: Streams) -> FitSummary:
    """Every reduction, over one decoded recording."""
    interval = _interval(streams.timestamps)
    step = interval or 1.0

    power = normalized_power(streams.power, interval_s=step)
    average_power = _present(streams.power)
    variability = (
        power / (sum(average_power) / len(average_power))
        if power is not None and average_power and sum(average_power) > 0
        else None
    )

    decouple, drift = decoupling(streams.heart_rate, streams.speed)
    up, down = climb(streams.altitude)
    path, count = route(streams.latitude, streams.longitude)

    return FitSummary(
        samples=len(streams),
        sample_interval_s=interval,
        normalized_power=power,
        variability_index=variability,
        decoupling_pct=decouple,
        hr_drift_bpm=drift,
        ascent_m=up,
        descent_m=down,
        moving_time_s=moving_time(streams.speed, interval_s=step),
        route_path=path,
        route_points=count,
    )


def parse(blob: bytes) -> FitSummary:
    """Bytes in, facts out. The streams never leave this call."""
    return summarise(decode(blob))

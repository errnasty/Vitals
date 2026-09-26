"""Decoding a recording, and the reductions that make it worth keeping.

Every test here runs against a FIT file this repository builds byte by byte — see
`fit_fixture` for why that is worth the trouble. The short version: the conventions a
FIT decoder gets wrong are all in the encoding (semicircles, altitude offsets,
millimetres per second), and only a real file can catch getting one of them wrong.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from tests.fit_fixture import build
from vitals.normalize import fit


def _points(count: int, **overrides: object) -> list[dict]:
    base = {
        "lat": 51.5,
        "lon": -0.12,
        "alt": 10.0,
        "hr": 140,
        "cad": 85,
        "speed": 3.0,
        "power": 200,
    }
    out = []
    for i in range(count):
        point = dict(base)
        point["dist"] = i * 3.0
        point.update({k: (v[i] if isinstance(v, list) else v) for k, v in overrides.items()})
        out.append(point)
    return out


def test_the_numbers_that_come_out_are_the_numbers_that_went_in() -> None:
    """Semicircles, the altitude offset and the speed scale, all at once."""
    streams = fit.decode(build(_points(3, alt=[10.0, 20.0, 30.0], hr=[120, 130, 140])))

    assert len(streams) == 3
    assert streams.heart_rate == [120.0, 130.0, 140.0]
    assert streams.altitude == [10.0, 20.0, 30.0]
    assert streams.speed == [3.0, 3.0, 3.0]
    assert streams.latitude[0] == pytest.approx(51.5, abs=1e-5)
    assert streams.longitude[0] == pytest.approx(-0.12, abs=1e-5)


def test_a_zipped_recording_is_unwrapped() -> None:
    """Garmin serves the original as a zip holding one .fit, never the file itself."""
    raw = build(_points(3))
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("12345.fit", raw)

    assert len(fit.decode(packed.getvalue())) == 3


def test_something_that_is_not_a_fit_file_is_refused_by_name() -> None:
    with pytest.raises(fit.UnreadableFit):
        fit.decode(b"this is not a recording")


def test_an_empty_zip_says_what_is_wrong() -> None:
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("readme.txt", "nothing here")

    with pytest.raises(fit.UnreadableFit, match="no .fit"):
        fit.decode(packed.getvalue())


# ── the reductions ──────────────────────────────────────────────────────────────


def test_normalized_power_exceeds_the_mean_on_a_surging_effort() -> None:
    """The whole reason the metric exists.

    Five minutes at 100W then five at 300W averages 200W, and costs far more than a
    steady 200 would. The fourth power is what makes the number say so.
    """
    surging = [100.0] * 300 + [300.0] * 300

    assert fit.normalized_power(surging, interval_s=1.0) == pytest.approx(251.7, abs=0.5)


def test_normalized_power_equals_the_mean_on_a_steady_effort() -> None:
    assert fit.normalized_power([200.0] * 300, interval_s=1.0) == pytest.approx(200.0)


def test_normalized_power_needs_a_full_window() -> None:
    """Ten seconds cannot produce a thirty-second rolling average, and must not try."""
    assert fit.normalized_power([200.0] * 10, interval_s=1.0) is None


def test_the_rolling_window_is_thirty_seconds_not_thirty_samples() -> None:
    """A watch recording every 5s would otherwise smooth over two and a half minutes."""
    # Blocks of ten. A thirty-sample window spans one and a half of them and flattens
    # the surge; a six-sample window leaves most of it standing.
    surging = ([100.0] * 10 + [300.0] * 10) * 12

    dense = fit.normalized_power(surging, interval_s=1.0)
    sparse = fit.normalized_power(surging, interval_s=5.0)

    assert dense is not None and sparse is not None
    # Measured in samples rather than seconds, both of these would be identical — and
    # a watch on smart recording would silently get the wrong number.
    assert sparse > dense + 10.0


def test_climb_ignores_altimeter_noise() -> None:
    """A barometer wandering half a metre must not become a mountain stage."""
    flat = [10.0, 10.4, 9.7, 10.2, 9.8, 10.3] * 50

    up, down = fit.climb(flat)

    assert up == 0.0
    assert down == 0.0


def test_climb_counts_a_real_hill() -> None:
    up, down = fit.climb([0.0, 25.0, 50.0, 25.0, 0.0])

    assert up == pytest.approx(50.0)
    assert down == pytest.approx(50.0)


def test_decoupling_is_positive_when_the_second_half_costs_more_heartbeats() -> None:
    """Same speed, drifting heart rate: the aerobic system giving way."""
    heart_rate = [140.0] * 200 + [160.0] * 200
    speed = [3.0] * 400

    percent, drift = fit.decoupling(heart_rate, speed)

    assert percent is not None and percent > 10.0
    assert drift == pytest.approx(20.0)


def test_decoupling_is_about_zero_on_a_steady_effort() -> None:
    percent, drift = fit.decoupling([140.0] * 400, [3.0] * 400)

    assert percent == pytest.approx(0.0, abs=0.01)
    assert drift == pytest.approx(0.0, abs=0.01)


def test_decoupling_refuses_a_sample_too_short_to_have_halves() -> None:
    assert fit.decoupling([140.0] * 20, [3.0] * 20) == (None, None)


def test_decoupling_uses_only_samples_where_both_channels_read() -> None:
    """A dropped strap in the second half would otherwise fake a large, confident number."""
    heart_rate: list[float | None] = [140.0] * 200 + [None] * 200
    speed: list[float | None] = [3.0] * 400

    percent, _ = fit.decoupling(heart_rate, speed)

    # 200 usable pairs, all identical: no decoupling, rather than a number invented
    # from the half that has no heart rate at all.
    assert percent == pytest.approx(0.0, abs=0.01)


# ── the route ───────────────────────────────────────────────────────────────────


def test_the_route_is_projected_into_the_design_system_s_box() -> None:
    """The component takes a finished path, like every other value it is handed."""
    points = _points(50, lat=[51.5 + i * 1e-4 for i in range(50)])

    summary = fit.parse(build(points))

    assert summary.route_path is not None
    assert summary.route_path.startswith("M")
    numbers = [
        float(part)
        for chunk in summary.route_path.replace("M", "").replace("L", "").split()
        for part in [chunk]
    ]
    xs, ys = numbers[0::2], numbers[1::2]
    assert all(0 <= x <= 380 for x in xs)
    assert all(0 <= y <= 300 for y in ys)


def test_longitude_is_squeezed_by_latitude_so_a_square_draws_square() -> None:
    """Without the cosine a loop at London's latitude comes out 60% too wide.

    A degree of longitude is shorter than a degree of latitude everywhere but the
    equator. These two legs cover the same number of *metres*; if the projection
    ignores that, they come out visibly different lengths.
    """
    import math

    mid = 51.5
    east_west_degrees = 0.001 / math.cos(math.radians(mid))
    points = [
        {
            "lat": mid,
            "lon": -0.12 + east_west_degrees * i / 25,
            "alt": 10.0,
            "hr": 140,
            "cad": 85,
            "speed": 3.0,
            "power": 200,
            "dist": i * 3.0,
        }
        for i in range(26)
    ] + [
        {
            "lat": mid + 0.001 * i / 25,
            "lon": -0.12 + east_west_degrees,
            "alt": 10.0,
            "hr": 140,
            "cad": 85,
            "speed": 3.0,
            "power": 200,
            "dist": (26 + i) * 3.0,
        }
        for i in range(26)
    ]

    path, _ = fit.route([p["lat"] for p in points], [p["lon"] for p in points])

    assert path is not None
    numbers = [float(p) for p in path.replace("M", "").replace("L", "").split()]
    xs, ys = numbers[0::2], numbers[1::2]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    assert width == pytest.approx(height, rel=0.02)


def test_an_indoor_activity_has_no_route_rather_than_a_dot() -> None:
    path, count = fit.route([None] * 100, [None] * 100)

    assert path is None
    assert count == 0


def test_a_long_route_is_downsampled_but_keeps_its_ends() -> None:
    lats = [51.5 + i * 1e-5 for i in range(2000)]
    lons = [-0.12 + i * 1e-5 for i in range(2000)]

    path, count = fit.route(lats, lons)

    assert path is not None
    assert count == fit.ROUTE_POINTS

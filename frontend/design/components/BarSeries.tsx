import type { CSSProperties } from "react";
import styles from "./BarSeries.module.css";

export type Bar = {
  value: number;
  /** `dim` for projected or partial, `muted` for a day with no data. */
  tone?: "accent" | "dim" | "muted";
  label?: string;
};

export type BarSeriesProps = {
  data: (number | Bar)[];
  /** Fixed scale ceiling. Defaults to the largest value in the series. */
  max?: number;
  height?: number;
  /** Two end captions under the bars — a range, not a full axis. */
  axis?: [string, string];
};

function toBar(item: number | Bar): Bar {
  return typeof item === "number" ? { value: item } : item;
}

/**
 * The bar strip that sits under a headline number: a week or a day, at a glance,
 * with no axis furniture competing with the figure above it.
 */
export function BarSeries({ data, max, height = 44, axis }: BarSeriesProps) {
  const bars = data.map(toBar);
  const ceiling = max ?? Math.max(...bars.map((bar) => bar.value), 1);

  return (
    <div>
      <div className={styles.bars} style={{ height }}>
        {bars.map((bar, index) => {
          const pct = ceiling > 0 ? Math.min(Math.max(bar.value / ceiling, 0), 1) : 0;
          const toneClass =
            bar.tone === "muted" ? styles.muted : bar.tone === "dim" ? styles.dim : "";
          return (
            <span
              key={index}
              className={[styles.bar, toneClass].filter(Boolean).join(" ")}
              data-motion="grow"
              // Each bar grows a beat after the one before it, left to right, so
              // the strip reads as a sequence rather than arriving as a block.
              style={
                {
                  height: `${pct * 100}%`,
                  animationDelay: `calc(var(--v-stagger) * ${index} / 2)`,
                } as CSSProperties
              }
              title={bar.label}
            />
          );
        })}
      </div>
      {axis ? (
        <div className={styles.axis}>
          <span>{axis[0]}</span>
          <span>{axis[1]}</span>
        </div>
      ) : null}
    </div>
  );
}

export type SparklineProps = {
  data: number[];
  width?: number;
  height?: number;
  /** Fill the area under the line. */
  area?: boolean;
};

/** A trend, not a chart: no axes, no ticks, no labels. */
export function Sparkline({ data, width = 120, height = 36, area = true }: SparklineProps) {
  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const step = width / (data.length - 1);
  const coords = data.map((value, index) => ({
    x: index * step,
    y: height - ((value - min) / span) * height,
  }));
  const points = coords.map(({ x, y }) => `${x.toFixed(2)},${y.toFixed(2)}`);

  // The drawn length of the polyline, so the dash animation has something exact to
  // work with. `getTotalLength()` would need a DOM node and a layout pass; the
  // segments are already here, and summing them is the same number.
  const length = coords.reduce((total, point, index) => {
    if (index === 0) return 0;
    const previous = coords[index - 1];
    return total + Math.hypot(point.x - previous.x, point.y - previous.y);
  }, 0);

  return (
    <svg
      className={styles.spark}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {area ? (
        <polygon
          className={styles.sparkArea}
          data-motion="fade"
          points={`0,${height} ${points.join(" ")} ${width},${height}`}
        />
      ) : null}
      <polyline
        className={styles.sparkLine}
        data-motion="draw"
        points={points.join(" ")}
        style={
          { strokeDasharray: length, "--v-draw-from": `${length}px` } as CSSProperties
        }
      />
    </svg>
  );
}

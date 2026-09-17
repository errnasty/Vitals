import styles from "./RouteMap.module.css";

/**
 * A boxy city loop — the default shape so the component renders something real
 * before there are GPS points to give it.
 */
const DEFAULT_ROUTE =
  "M74 250 L74 156 L134 156 L134 92 L196 92 L196 46 L282 46 L282 128 L232 128 L232 184 L312 184 L312 252 L188 252 L188 208 L126 208 L126 250 Z";

export type RouteLabel = {
  text: string;
  x: number;
  y: number;
  /** Degrees, for a street name that runs along its street. */
  rotate?: number;
};

export type RouteMapProps = {
  /** SVG path data in a 380x300 viewBox. Defaults to the placeholder loop. */
  path?: string;
  labels?: RouteLabel[];
  height?: number;
};

const DEFAULT_LABELS: RouteLabel[] = [
  { text: "Chesapeake Avenue", x: 344, y: 108, rotate: 90 },
  { text: "Marsh Street", x: 42, y: 196, rotate: -90 },
  { text: "Rowan Park", x: 190, y: 282 },
];

/**
 * The activity route. Drawn, not tiled: no map provider, no API key, and no
 * network request on a screen whose job is to show one line.
 */
export function RouteMap({ path = DEFAULT_ROUTE, labels = DEFAULT_LABELS, height }: RouteMapProps) {
  return (
    <div className={styles.wrap} style={height ? { height } : undefined}>
      <svg className={styles.svg} viewBox="0 0 380 300" role="img" aria-label="Activity route">
        {/* Block grid */}
        <g className={styles.grid}>
          {[0, 1, 2, 3, 4, 5, 6].map((i) => (
            <line key={`h${i}`} x1="0" y1={i * 50} x2="380" y2={i * 50} />
          ))}
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <line key={`v${i}`} x1={i * 54} y1="0" x2={i * 54} y2="300" />
          ))}
        </g>

        {/* A couple of wider roads, so the route reads as running along streets */}
        <g className={styles.street}>
          <path d="M0 156 H380" />
          <path d="M196 0 V300" />
        </g>

        {/* Casing first, then the line: the route stays legible over a street */}
        <path className={styles.routeCasing} d={path} />
        <path className={styles.route} d={path} />

        <circle className={styles.marker} cx="74" cy="250" r="7" />
        <circle className={styles.markerEnd} cx="126" cy="250" r="7" />

        {labels.map((label) => (
          <text
            key={label.text}
            className={styles.label}
            x={label.x}
            y={label.y}
            textAnchor="middle"
            transform={label.rotate ? `rotate(${label.rotate} ${label.x} ${label.y})` : undefined}
          >
            {label.text}
          </text>
        ))}
      </svg>
      <div className={styles.scrim} />
    </div>
  );
}

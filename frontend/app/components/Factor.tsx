import { Badge, Card, CardHeader } from "@/design";
import type { FactorView } from "@/app/lib/api";
import prose from "./Prose.module.css";
import styles from "./Factor.module.css";

/**
 * One input to a pillar, explained rather than just listed.
 *
 * Four things, in the order someone actually asks them: what it is now, how it is
 * being graded, what full marks look like, and what would move it. Every one of them
 * arrives from the API as a finished string — including the points, the target and
 * the sentence of advice — because working out "8h would be worth 2.1 points" is
 * arithmetic, and this file has none in it.
 *
 * `target` is deliberately absent on some rows. Overnight HRV has no number to aim
 * for; presenting one would teach the reader to chase a reading they do not control.
 */
export function Factor({ factor }: { factor: FactorView }) {
  return (
    <Card>
      <CardHeader
        title={factor.label}
        subtitle={factor.rationale}
        action={
          <Badge tone={factor.points_value >= 70 ? "accent" : "neutral"}>
            {factor.points}
          </Badge>
        }
      />

      <dl className={styles.grid}>
        <div className={styles.cell}>
          <dt className={styles.key}>Now</dt>
          <dd className={styles.val}>{factor.value}</dd>
        </div>
        {factor.target ? (
          <div className={styles.cell}>
            <dt className={styles.key}>Full marks</dt>
            <dd className={styles.val}>{factor.target}</dd>
          </div>
        ) : null}
        <div className={styles.cell}>
          <dt className={styles.key}>Worth now</dt>
          <dd className={styles.val}>{factor.effect}</dd>
        </div>
        {factor.headroom_value >= 0.5 ? (
          <div className={styles.cell}>
            <dt className={styles.key}>Available</dt>
            <dd className={`${styles.val} ${styles.gain}`}>+{factor.headroom}</dd>
          </div>
        ) : null}
      </dl>

      <p className={prose.note}>
        {factor.basis}
        {factor.scale ? ` — ${factor.scale}` : ""}.
      </p>

      {factor.advice ? <p className={styles.advice}>{factor.advice}</p> : null}
    </Card>
  );
}

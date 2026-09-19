import { Card, CardHeader } from "@/design";
import styles from "./Prose.module.css";

export type BriefProps = {
  body: string;
  /**
   * The day the brief describes, already formatted — passed only when it is not the
   * day the screen is already showing, so the date never appears twice.
   */
  when?: string;
};

/**
 * The day's note, read from the API.
 *
 * Deliberately undecorated: no avatar, no "AI" badge, no sparkle animation. The
 * sentence either says something useful or it does not, and dressing it up as a
 * conversation with a machine would invite the reader to treat it as one. It is a
 * caption on the number above it.
 *
 * Nothing here indicates whether a model or Python wrote it. The API knows, and the
 * CLI reports it, but to the person reading it the only thing that matters is that
 * every number in it was computed by Python and checked before it was stored — which
 * is true either way.
 */
export function Brief({ body, when }: BriefProps) {
  return (
    <Card>
      <CardHeader title="The short version" icon="sparkle" subtitle={when} />
      <p className={styles.body}>{body}</p>
    </Card>
  );
}

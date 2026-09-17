import { Card, CardHeader, Stat } from "@/design";
import type { IconName } from "@/design";

export type NoticeProps = {
  title: string;
  body: string;
  icon?: IconName;
  /** A command to run, shown verbatim. */
  command?: string;
};

/**
 * What the screen says when there is nothing to draw.
 *
 * Deliberately not a spinner and not a row of dashes. The two states this app can
 * legitimately be in early on — no data yet, or the API unreachable — are completely
 * different problems, and a dash looks identical for both. So the reason is the
 * content, and where there is a command that fixes it, it is on screen.
 */
export function Notice({ title, body, icon = "sparkle", command }: NoticeProps) {
  return (
    <Card>
      <CardHeader title={title} icon={icon} />
      <Stat value={body} size="xs" caption={command ? `Run: ${command}` : undefined} />
    </Card>
  );
}

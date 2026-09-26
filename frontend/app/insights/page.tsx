import {
  AppShell,
  Badge,
  BottomNav,
  Card,
  CardHeader,
  Gutter,
  Stack,
  ThemeToggle,
  TopBar,
} from "@/design";
import { Notice } from "@/app/components/Notice";
import { fetchInsights } from "@/app/lib/api";
import { navFor } from "@/app/lib/nav";
import prose from "@/app/components/Prose.module.css";
import styles from "./insights.module.css";

export const dynamic = "force-dynamic";

/**
 * What the analysis found — and what it is honest about not finding.
 *
 * This screen is designed around the empty case, because the empty case is the
 * normal one. Most people, most of the time, have no detectable effects: either
 * there genuinely are none, or a few weeks of tagged days cannot show one. A
 * patterns screen that always has something to say is one that is making things up,
 * so the two reasons for having nothing get two different explanations, and neither
 * of them is a blank page.
 *
 * Every number here arrives as part of a finished sentence. Nothing on this page
 * computes a percentage, ranks a finding or decides what counts as strong — that all
 * happened in Python, against the same statistics that produced the finding, which
 * is the only way the screen and the analysis cannot disagree.
 */
export default async function InsightsPage() {
  const result = await fetchInsights();
  const nav = <BottomNav items={navFor("insights")} />;

  if (!result.ok) {
    return (
      <AppShell header={<TopBar title="Patterns" centered />} nav={nav}>
        <Gutter>
          <Notice title="Can't reach the API" body={result.error} icon="pulse" />
        </Gutter>
      </AppShell>
    );
  }

  const { findings, tested, empty_reason: emptyReason } = result.data;

  return (
    <AppShell
      header={<TopBar title="Patterns" eyebrow="What your days do" right={<ThemeToggle />} />}
      nav={nav}
    >
      <Gutter>
        <Stack>
          {findings.length === 0 ? (
            <Card>
              <CardHeader title="Nothing to report" icon="sparkle" />
              <p className={prose.note}>{emptyReason}</p>
            </Card>
          ) : (
            <Card>
              <CardHeader title="What holds up" icon="sparkle" />
              <div>
                {findings.map((finding) => (
                  <article
                    key={`${finding.tag}:${finding.metric}:${finding.when}`}
                    className={styles.finding}
                  >
                    <p className={styles.sentence}>{finding.sentence}</p>
                    <div className={styles.evidence}>
                      {/* Neutral on purpose. "Higher" is good for HRV and bad for
                          resting heart rate, and the analysis never said which this
                          is — colouring it here would be the screen inventing a
                          verdict the statistics did not reach. */}
                      <Badge tone="neutral">{finding.change}</Badge>
                      <span className={styles.evidenceText}>
                        {finding.sample} &middot; {finding.confidence}
                      </span>
                    </div>
                  </article>
                ))}
              </div>
            </Card>
          )}

          <Card>
            <CardHeader title="How to read this" icon="chart" />
            <p className={prose.note}>
              These come from your own days, compared against each other — not from a
              study, and not from anyone else&rsquo;s data. A tagged day is only
              compared with your untagged ones, so the answer is about you.
            </p>
            <p className={prose.note}>
              Nothing here is a cause. Late nights and alcohol arrive together often
              enough that either can take the credit for the other, and this cannot
              tell them apart.
            </p>
            {tested > 0 ? (
              <p className={styles.denominator}>
                This run performed {tested} tests and reported {findings.length}.
                Testing that many things turns up coincidences on its own, so the bar
                is raised to account for every test that was run — including the ones
                you never see.
              </p>
            ) : null}
          </Card>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

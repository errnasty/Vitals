import {
  AppShell,
  BottomNav,
  Card,
  CardHeader,
  Gutter,
  ProgressRing,
  ScoreGauge,
  SectionHeader,
  Stack,
  Stat,
  ThemeToggle,
  TopBar,
} from "@/design";
import { Factor } from "@/app/components/Factor";
import { Notice } from "@/app/components/Notice";
import { fetchScoreDetail } from "@/app/lib/api";
import { longDate, pillarIcon } from "@/app/lib/display";
import { navFor } from "@/app/lib/nav";
import prose from "@/app/components/Prose.module.css";
import styles from "./method.module.css";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ day?: string }>;

/**
 * The score, explained — how it is built, what it is built from, and what would move it.
 *
 * Three questions in the order people ask them. *What is this number* comes first,
 * because a score you cannot interrogate is a score you should not trust. *What is it
 * made of* is four tiles, each a way into its own screen. *What would help* is last
 * and is ranked by points recoverable rather than by what scored worst — a weak line
 * that barely counts is not where anyone's week should go, and only Python knows
 * which is which.
 */
export default async function ScorePage({ searchParams }: { searchParams: SearchParams }) {
  const { day } = await searchParams;
  const result = await fetchScoreDetail(day);
  const nav = <BottomNav items={navFor("score")} />;

  if (!result.ok) {
    return (
      <AppShell header={<TopBar title="Breakdown" centered />} nav={nav}>
        <Gutter>
          <Notice title="No breakdown to show" body={result.error} icon="target" />
        </Gutter>
      </AppShell>
    );
  }

  const { date, value, caption, coverage, trusted, method, pillars, opportunities } =
    result.data;

  return (
    <AppShell
      header={
        <TopBar title="Breakdown" eyebrow={longDate(date)} right={<ThemeToggle />} />
      }
      nav={nav}
    >
      <Gutter>
        <ScoreGauge value={value} label="Vitals Score" caption={caption} size={180} />

        <Stack>
          {trusted ? null : (
            <Notice
              title="Limited data"
              body={`Only ${coverage} of the inputs this score wants were available. It is shown so you can watch it settle, not to be acted on yet.`}
              icon="sparkle"
            />
          )}

          <SectionHeader title="What it is made of" />
          {pillars.map((pillar) => (
            <Card key={pillar.name} href={`/score/${pillar.name}`}>
              <CardHeader
                title={pillar.label}
                subtitle={`${pillar.weight} of the score · ${pillar.coverage} of its inputs available`}
                icon={pillarIcon(pillar.name)}
                // The ring carries the number. A badge beside it would be the same
                // figure twice, which reads as two different measurements.
                action={
                  <ProgressRing
                    value={pillar.value}
                    size={48}
                    label={`${pillar.label} ${pillar.display} of 100`}
                  />
                }
              />
              <p className={prose.note}>{pillar.summary}</p>
            </Card>
          ))}

          {opportunities.length ? (
            <>
              <SectionHeader title="Where the points are" />
              <Card variant="flat" padding="sm">
                <Stat
                  value="Ranked by what would move the score"
                  size="xs"
                  caption="Not by what scored worst — a weak line that barely counts is not worth your week."
                />
              </Card>
              {opportunities.map((factor) => (
                <Factor key={factor.metric} factor={factor} />
              ))}
            </>
          ) : null}

          <SectionHeader title="How it is calculated" />
          <Card>
            <CardHeader title={method.headline} icon="target" />
            <ol className={styles.steps}>
              {method.steps.map((step) => (
                <li key={step} className={styles.step}>
                  {step}
                </li>
              ))}
            </ol>
            <p className={prose.note}>{method.coverage_floor}</p>
          </Card>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

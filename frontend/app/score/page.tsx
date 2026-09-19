import {
  AppShell,
  BottomNav,
  Badge,
  Card,
  CardHeader,
  Gutter,
  ListRow,
  ProgressRing,
  SectionHeader,
  Stack,
  Stat,
  ScoreGauge,
  TopBar,
} from "@/design";
import { Notice } from "@/app/components/Notice";
import { fetchExplain } from "@/app/lib/api";
import type { ContributionView } from "@/app/lib/api";
import { longDate, pillarIcon } from "@/app/lib/display";
import { navFor } from "@/app/lib/nav";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ day?: string }>;

/**
 * The breakdown — why the number is the number.
 *
 * Every line shows what was measured, what it scored, and how many points of the
 * final total it is responsible for. Those effects sum to the score exactly, because
 * Python worked them out that way; this page does no arithmetic to present them, it
 * only groups them under their pillar.
 */
export default async function ScorePage({ searchParams }: { searchParams: SearchParams }) {
  const { day } = await searchParams;
  const result = await fetchExplain(day);
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

  const { score, pillars, contributions, date } = result.data;
  const byPillar = new Map<string, ContributionView[]>();
  for (const item of contributions) {
    byPillar.set(item.pillar, [...(byPillar.get(item.pillar) ?? []), item]);
  }

  return (
    <AppShell
      header={<TopBar title="Breakdown" eyebrow={longDate(date)} centered />}
      nav={nav}
    >
      <Gutter>
        <ScoreGauge
          value={score.value}
          label="Vitals Score"
          rating={score.rating}
          caption={score.caption}
          size={180}
        />

        <Stack>
          {!score.trusted ? (
            <Card variant="flat">
              <Stat
                icon="sparkle"
                value="Limited data"
                size="xs"
                caption={`Only ${score.coverage} of the inputs this score wants were available. It is shown so you can watch it settle, not to be acted on yet.`}
              />
            </Card>
          ) : null}

          <SectionHeader title="Where the points came from" />

          {pillars.map((pillar) => {
            const lines = byPillar.get(pillar.name) ?? [];
            return (
              <Card key={pillar.name}>
                <CardHeader
                  title={pillar.label}
                  subtitle={`${pillar.coverage} of its inputs available`}
                  icon={pillarIcon(pillar.name)}
                  action={
                    <ProgressRing
                      value={pillar.value}
                      size={48}
                      label={`${pillar.label} ${pillar.display} of 100`}
                    />
                  }
                />
                {lines.map((line) => (
                  <ListRow
                    key={line.metric}
                    label={line.label}
                    meta={`${line.value} · scored ${line.points}`}
                    value={
                      <Badge tone={line.points_value >= 50 ? "accent" : "neutral"}>
                        {line.effect} pts
                      </Badge>
                    }
                  />
                ))}
              </Card>
            );
          })}

          <Card variant="flat" padding="sm">
            <Stat
              value="Every line above is worth the points it says"
              size="xs"
              caption="The effects add up to the score exactly — they are the decomposition, not an estimate of one."
            />
          </Card>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

import {
  AppShell,
  Badge,
  BottomNav,
  Button,
  Card,
  CardHeader,
  Gutter,
  ListRow,
  ProgressRing,
  SectionHeader,
  Stack,
  ThemeToggle,
  TopBar,
} from "@/design";
import { Factor } from "@/app/components/Factor";
import { Notice } from "@/app/components/Notice";
import { fetchPillar } from "@/app/lib/api";
import { longDate, pillarIcon } from "@/app/lib/display";
import { navFor } from "@/app/lib/nav";
import prose from "@/app/components/Prose.module.css";

export const dynamic = "force-dynamic";

type Params = Promise<{ pillar: string }>;
type Search = Promise<{ day?: string }>;

/**
 * One pillar in full — what it measures, what it is made of, and what would move it.
 *
 * This is the screen the Today tiles lead to, and the reason the score is stored
 * decomposed rather than as a number: every figure here is a column, not a
 * calculation. The targets come from the same calibration the score was computed
 * with, so the page cannot tell you to aim at something the scoring did not use.
 */
export default async function PillarPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Search;
}) {
  const { pillar: name } = await params;
  const { day } = await searchParams;
  const result = await fetchPillar(name, day);
  const nav = <BottomNav items={navFor("score")} />;

  if (!result.ok) {
    return (
      <AppShell header={<TopBar title="Pillar" centered />} nav={nav}>
        <Gutter>
          <Notice title="Nothing to show" body={result.error} icon="target" />
        </Gutter>
      </AppShell>
    );
  }

  const { pillar, date } = result.data;

  return (
    <AppShell
      header={
        <TopBar
          title={pillar.label}
          eyebrow={longDate(date)}
          right={<ThemeToggle />}
        />
      }
      nav={nav}
    >
      <Gutter>
        <Stack>
          <Card>
            <CardHeader
              title={`${pillar.display} out of 100`}
              subtitle={`${pillar.weight} of the day's score · ${pillar.coverage} of its inputs available`}
              icon={pillarIcon(pillar.name)}
              action={
                <ProgressRing
                  value={pillar.value}
                  size={56}
                  label={`${pillar.label} ${pillar.display} of 100`}
                />
              }
            />
            <p className={prose.note}>{pillar.summary}</p>
          </Card>

          {pillar.reference ? (
            <Card>
              <CardHeader
                title={pillar.reference.label}
                subtitle={longDate(pillar.reference.date)}
                icon="moon"
                action={<Badge tone="neutral">{pillar.reference.value}</Badge>}
              />
              <p className={prose.note}>{pillar.reference.explanation}</p>
            </Card>
          ) : null}

          {pillar.readings.length ? (
            <Card padding="sm">
              <CardHeader title="Measured" icon="pulse" />
              {pillar.readings.map((reading) => (
                <ListRow
                  key={reading.label}
                  label={reading.label}
                  value={reading.value}
                />
              ))}
            </Card>
          ) : null}

          {pillar.trusted ? null : (
            <Notice
              title="Limited data"
              body={`Only ${pillar.coverage} of this pillar's inputs were available. Read it loosely.`}
              icon="sparkle"
            />
          )}

          <SectionHeader title="What it is made of" />
          {pillar.factors.map((factor) => (
            <Factor key={factor.metric} factor={factor} />
          ))}

          <Button href="/score" variant="quiet" block>
            Back to the breakdown
          </Button>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

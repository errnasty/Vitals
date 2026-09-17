import {
  AppShell,
  Badge,
  BottomNav,
  Card,
  CardHeader,
  Grid2,
  Gutter,
  ListRow,
  SectionHeader,
  Sparkline,
  Stack,
  Stat,
  ScoreGauge,
  ThemeToggle,
  TopBar,
} from "@/design";
import { Notice } from "@/app/components/Notice";
import { fetchToday } from "@/app/lib/api";
import { headlineIcon, longDate, pillarIcon } from "@/app/lib/display";
import { navFor } from "@/app/lib/nav";

export const dynamic = "force-dynamic";

/**
 * Today — what the app opens on.
 *
 * One score owns the screen and everything under it says what the score is made of,
 * which is the shape the design system's reference screen set out. Every value here
 * arrives from the API already formatted: there is not a single calculation on this
 * page, by design.
 */
export default async function Page() {
  const result = await fetchToday();

  const header = (
    <TopBar
      title="Today"
      eyebrow={result.ok && result.data.date ? longDate(result.data.date) : "Vitals"}
      right={<ThemeToggle />}
    />
  );
  const nav = <BottomNav items={navFor("today")} />;

  if (!result.ok) {
    return (
      <AppShell header={header} nav={nav}>
        <Gutter>
          <Notice title="Can't reach the API" body={result.error} icon="pulse" />
        </Gutter>
      </AppShell>
    );
  }

  const { score, pillars, headlines, trend, empty_reason } = result.data;

  if (!score) {
    return (
      <AppShell header={header} nav={nav}>
        <Gutter>
          <Notice
            title="Nothing to show yet"
            body={empty_reason ?? "No score has been computed."}
            command={empty_reason?.includes("vitals score") ? "vitals score" : "vitals sync"}
          />
        </Gutter>
      </AppShell>
    );
  }

  return (
    <AppShell header={header} nav={nav}>
      <Gutter>
        <ScoreGauge
          value={score.value}
          label="Vitals Score"
          rating={score.rating}
          caption={score.caption}
        />

        <Stack>
          {trend.length > 1 ? (
            <Card>
              <CardHeader
                title="Last two weeks"
                icon="chart"
                action={
                  <Badge tone={score.trusted ? "accent" : "neutral"}>
                    {score.coverage} covered
                  </Badge>
                }
              />
              <Sparkline data={trend} area />
            </Card>
          ) : null}

          <SectionHeader title="Pillars" action="Breakdown" actionHref="/score" />
          <Grid2>
            {pillars.map((pillar) => (
              <Card key={pillar.name} padding="sm" href="/score">
                <Stat
                  icon={pillarIcon(pillar.name)}
                  label={pillar.label}
                  value={pillar.display}
                  size="sm"
                  accent={pillar.value >= 80}
                  caption={pillar.coverage === "100%" ? undefined : `${pillar.coverage} covered`}
                />
              </Card>
            ))}
          </Grid2>

          {headlines.length ? (
            <>
              <SectionHeader title="Measurements" action="Trends" actionHref="/trends" />
              <Card padding="sm">
                {headlines.map((item) => (
                  <ListRow
                    key={item.key}
                    icon={headlineIcon(item.key)}
                    label={item.label}
                    meta={item.meta ?? undefined}
                    value={item.value}
                  />
                ))}
              </Card>
            </>
          ) : null}
        </Stack>
      </Gutter>
    </AppShell>
  );
}

import {
  AppShell,
  BarSeries,
  BottomNav,
  Card,
  CardHeader,
  Gutter,
  SegmentedControl,
  SectionHeader,
  Sparkline,
  Stack,
  Stat,
  TopBar,
} from "@/design";
import { Notice } from "@/app/components/Notice";
import { fetchTrends } from "@/app/lib/api";
import { shortDate } from "@/app/lib/display";
import { navFor } from "@/app/lib/nav";

export const dynamic = "force-dynamic";

// Above this many days, individual bars stop being legible on a phone.
const BAR_LIMIT = 31;

const WINDOWS = [
  { value: "30", label: "30d" },
  { value: "90", label: "90d" },
  { value: "365", label: "1y" },
];

type SearchParams = Promise<{ days?: string }>;

/**
 * Trends — the long view.
 *
 * The score at the top, then the derived series behind it. A single day's score is
 * noisier than the shape of a season, and this is the screen that shows the shape.
 */
export default async function TrendsPage({ searchParams }: { searchParams: SearchParams }) {
  const { days } = await searchParams;
  const window = WINDOWS.some((option) => option.value === days) ? days! : "90";
  const result = await fetchTrends(Number(window));
  const nav = <BottomNav items={navFor("trends")} />;

  const header = <TopBar title="Trends" eyebrow={`Last ${window} days`} />;

  if (!result.ok) {
    return (
      <AppShell header={header} nav={nav}>
        <Gutter>
          <Notice title="No trends to show" body={result.error} icon="chart" />
        </Gutter>
      </AppShell>
    );
  }

  const { score, series } = result.data;

  return (
    <AppShell header={header} nav={nav}>
      <Gutter>
        <Stack>
          <SegmentedControl
            options={WINDOWS}
            value={window}
            hrefFor={(value) => `/trends?days=${value}`}
          />

          {score.length > 1 ? (
            <Card>
              <CardHeader title="Vitals Score" icon="target" />
              {/* Bars up to a month, where each one is a readable day against the
                  full 0-100 scale. Past that they collapse into a picket fence, and
                  the shape of the season is what the screen is actually for. */}
              {score.length <= BAR_LIMIT ? (
                <BarSeries
                  data={score.map((point) => point.value)}
                  max={100}
                  height={72}
                  axis={[shortDate(score[0].date), shortDate(score[score.length - 1].date)]}
                />
              ) : (
                <Sparkline data={score.map((point) => point.value)} area />
              )}
            </Card>
          ) : (
            <Notice
              title="Not enough history yet"
              body="The score needs a few days before a trend means anything."
              icon="chart"
            />
          )}

          {series.length ? <SectionHeader title="Behind the score" /> : null}

          {series.map((item) => (
            <Card key={item.metric}>
              <CardHeader title={item.label} />
              <Stat value={item.latest} size="sm" labelBelow />
              <Sparkline data={item.points.map((point) => point.value)} area />
            </Card>
          ))}
        </Stack>
      </Gutter>
    </AppShell>
  );
}

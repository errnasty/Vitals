import {
  AppShell,
  BarSeries,
  BottomNav,
  NavAction,
  Card,
  CardHeader,
  Gutter,
  Grid2,
  IconButton,
  ProgressRing,
  ScoreGauge,
  SectionHeader,
  Stack,
  Stat,
  TopBar,
} from "../..";
import { NAV_ITEMS } from "./nav";

const MOVE_BARS = [
  32, 48, 41, 66, 58, 74, 62, 88, 71, 54,
  { value: 46, tone: "dim" as const },
  { value: 30, tone: "dim" as const },
  { value: 18, tone: "muted" as const },
  { value: 12, tone: "muted" as const },
];

/**
 * Screen 2 — the state of the day. One score owns the screen; everything below
 * it exists to say what the score is made of.
 */
export function StateScreen() {
  return (
    <AppShell
      header={
        <TopBar
          title="Current State"
          eyebrow="Tuesday, 17 Sep"
          right={<IconButton icon="user" label="Profile" />}
        />
      }
      nav={
        <BottomNav
          items={NAV_ITEMS.map((item) => ({ ...item, active: item.id === "trends" }))}
          action={<NavAction icon="play" label="Start an activity" />}
        />
      }
    >
      <Gutter>
        <ScoreGauge value={75} label="Vitals Score" rating={2} caption="Balanced" />

        <Stack>
          <Card>
            <Grid2>
              <Stat icon="flame" label="Move" value="220" target="1 750 kcal" size="sm" />
              <Stat icon="dumbbell" label="Exercise" value="40" target="280 min" size="sm" />
            </Grid2>
            <div style={{ marginTop: "var(--v-s-5)" }}>
              <BarSeries data={MOVE_BARS} height={52} axis={["00:00", "now"]} />
            </div>
          </Card>

          <Card href="#">
            <CardHeader
              title="Monday Morning Run"
              subtitle="Yesterday · 07:12"
              icon="run"
              action={<ProgressRing value={68} size={46} label="68 percent of weekly target" />}
            />
            <Stat value="10,58" unit="km" size="sm" caption="40:28 · 3:49 /km · 108 bpm avg" />
          </Card>

          <SectionHeader title="Pillars" action="Breakdown" actionHref="#" />

          <Grid2>
            <Card padding="sm">
              <Stat icon="moon" label="Recovery" value="80" size="sm" accent />
            </Card>
            <Card padding="sm">
              <Stat icon="bolt" label="Load" value="62" size="sm" />
            </Card>
            <Card padding="sm">
              <Stat icon="drop" label="Sleep" value="88" size="sm" />
            </Card>
            <Card padding="sm">
              <Stat icon="target" label="Body" value="71" size="sm" />
            </Card>
          </Grid2>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

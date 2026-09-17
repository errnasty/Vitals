import {
  AppShell,
  Badge,
  BarSeries,
  Button,
  Card,
  CardHeader,
  Gutter,
  IconButton,
  ListRow,
  RouteMap,
  SectionHeader,
  Stack,
  Stat,
  StatGroup,
  TopBar,
} from "../..";

const SPLITS = [72, 78, 74, 81, 86, 79, 88, 92, 84, 76];

/**
 * Screen 3 — one activity. The duration is the headline; the route is the
 * evidence; the splits are the detail you scroll for.
 */
export function ActivityScreen() {
  return (
    <AppShell
      header={
        <TopBar
          centered
          title="Monday Morning Run"
          left={<IconButton icon="chevronLeft" label="Back" />}
          right={<IconButton icon="share" label="Share activity" />}
        />
      }
    >
      <Gutter>
        <RouteMap />

        <div style={{ textAlign: "center", padding: "var(--v-s-6) 0 var(--v-s-5)" }}>
          <Stat value="40:28:02" label="Duration" size="lg" labelBelow />
        </div>

        <Card>
          <StatGroup divided>
            <Stat label="Energy" value="220" unit="kcal" size="xs" />
            <Stat label="Distance" value="10,58" unit="km" size="xs" />
            <Stat label="Avg HR" value="108" unit="bpm" size="xs" />
          </StatGroup>
        </Card>

        <SectionHeader title="Splits" action="Per km" />
        <Stack>
          <Card>
            <CardHeader
              title="Pace held to plan"
              subtitle="3:49 /km average · 4 s drift"
              icon="pulse"
              action={<Badge>Even</Badge>}
            />
            <BarSeries data={SPLITS} height={56} axis={["km 1", "km 10"]} />
          </Card>

          <Card padding="sm">
            <ListRow icon="bolt" label="Training effect" meta="Aerobic 3.4 · anaerobic 1.1" value="3.4" />
            <ListRow icon="lungs" label="Est. VO₂max" meta="Up 0.6 over 30 days" value="54.2" />
            <ListRow icon="clock" label="Recovery time" meta="Clear by 21:00 tonight" value="14 h" />
          </Card>

          <Button icon="play" block size="lg">
            Repeat this session
          </Button>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

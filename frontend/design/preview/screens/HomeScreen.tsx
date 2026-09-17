import {
  AppShell,
  BottomNav,
  NavAction,
  Badge,
  Card,
  CardHeader,
  Chip,
  ChipRow,
  Gutter,
  Hero,
  IconButton,
  ListRow,
  ProgressRing,
  SectionHeader,
  Stack,
  Stat,
  Sparkline,
} from "../..";
import { NAV_ITEMS } from "./nav";

/**
 * Screen 1 — the greeting. What the app opens on: one sentence about today,
 * four ways to steer it, and the day's measurements a scroll below.
 */
export function HomeScreen() {
  return (
    <AppShell
      nav={
        <BottomNav
          items={NAV_ITEMS.map((item) => ({ ...item, active: item.id === "today" }))}
          action={<NavAction icon="plus" label="Log something" />}
        />
      }
    >
      <Hero
        eyebrow="Tuesday, 17 September"
        title={
          <>
            Morning,
            <strong>Steve</strong>
          </>
        }
        body="Recovery is ahead of your seven-day average and load is light. A hard session would land well today."
        topLeft={<Badge icon="sparkle">Vitals brief</Badge>}
        topRight={<IconButton icon="grid" label="Open menu" />}
        chips={
          <ChipRow>
            <Chip dot selected>
              Energise
            </Chip>
            <Chip dot>Recover</Chip>
            <Chip dot>Focus</Chip>
            <Chip dot>Calm</Chip>
          </ChipRow>
        }
        actions={
          <>
            <IconButton icon="share" label="Share brief" size="lg" />
            <IconButton icon="chevronRight" label="Read the full brief" tone="accent" size="lg" />
          </>
        }
      />

      <Gutter>
        <SectionHeader title="Today" action="All metrics" actionHref="#" />
        <Stack>
          <Card>
            <CardHeader
              title="Readiness"
              subtitle="HRV 74 ms · resting HR 48 bpm"
              icon="bolt"
              action={<ProgressRing value={82} size={52} label="Readiness 82 of 100" />}
            />
            <Sparkline data={[58, 61, 57, 66, 70, 68, 74, 71, 79, 82]} />
          </Card>

          <Card padding="sm">
            <ListRow icon="moon" label="Sleep" meta="7 h 42 m · 91% efficiency" value="Good" href="#" />
            <ListRow icon="heart" label="Resting HR" meta="Down 2 bpm this week" value="48" href="#" />
            <ListRow icon="scale" label="Body" meta="Trend −0.4 kg / 14 d" value="78.2" href="#" />
          </Card>

          <Card variant="accent">
            <CardHeader title="Suggested session" subtitle="From your response profile" icon="run" />
            <Stat
              value="45"
              unit="min"
              caption="Zone 2 endurance — the session your last four weeks respond to best."
            />
          </Card>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

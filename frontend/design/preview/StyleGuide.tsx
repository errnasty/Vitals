import type { ReactNode } from "react";
import {
  BarSeries,
  Badge,
  Button,
  Card,
  CardHeader,
  Chip,
  Delta,
  Icon,
  IconButton,
  ListRow,
  ProgressRing,
  ScoreGauge,
  SegmentedControl,
  Sparkline,
  Stat,
  StatGroup,
  ThemeToggle,
  iconNames,
} from "..";
import { radii, tokenGroups, typeScale } from "../tokens";
import { PhoneFrame } from "./PhoneFrame";
import { ActivityScreen } from "./screens/ActivityScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { StateScreen } from "./screens/StateScreen";
import styles from "./StyleGuide.module.css";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {children}
    </section>
  );
}

function Swatches({ tokens }: { tokens: readonly string[] }) {
  return (
    <div className={styles.swatches}>
      {tokens.map((token) => (
        <div key={token} className={styles.swatch}>
          <div className={styles.chipColor} style={{ background: `var(${token})` }} />
          <div className={styles.swatchName}>{token}</div>
        </div>
      ))}
    </div>
  );
}

/**
 * The living reference for the Vitals design system: the tokens, every
 * primitive, and the three reference screens they compose into.
 *
 * It renders from the same exports the app uses, so it cannot drift — if a
 * component changes, this page changes with it.
 */
export function StyleGuide() {
  return (
    <div className={styles.page}>
      <header className={styles.lede}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>
            Vitals <em>design system</em>
          </h1>
          <ThemeToggle size="lg" />
        </div>
        <p className={styles.sub}>
          Dark by default, light when you ask for it. One accent per theme, set in a
          serif, with numbers as the subject. Everything on this page lives in{" "}
          <code>frontend/design/</code> and is imported through a single path.
        </p>
        <p className={styles.note}>
          <strong>The contract.</strong> Feature code imports from <code>@/design</code> and
          never reaches deeper. Styling lives here; data and routing live in{" "}
          <code>app/</code>. Keeping those apart is what lets a design change and a feature
          branch land in either order without touching the same lines.
        </p>
        <p className={styles.note}>
          <strong>Two themes.</strong> The switch above flips the whole page. Light is not
          an inversion — lime on white is unreadable, so the light theme takes a deep green
          of the same family, and every text colour in both themes clears WCAG AA against
          its own canvas. Without an explicit choice the app follows the operating system.
        </p>
      </header>

      <Section title="Reference screens">
        <div className={styles.screens}>
          <PhoneFrame caption="Today">
            <HomeScreen />
          </PhoneFrame>
          <PhoneFrame caption="Current state">
            <StateScreen />
          </PhoneFrame>
          <PhoneFrame caption="Activity detail">
            <ActivityScreen />
          </PhoneFrame>
        </div>
      </Section>

      <Section title="Colour">
        <Swatches tokens={tokenGroups.surface} />
        <Swatches tokens={tokenGroups.accent} />
        <Swatches tokens={tokenGroups.semantic} />
        <Swatches tokens={tokenGroups.series} />
      </Section>

      <Section title="Type">
        {typeScale.map((entry) => (
          <div key={entry.token} className={styles.typeRow}>
            <span className={styles.typeToken}>{entry.token}</span>
            <span
              style={{
                fontSize: `var(${entry.token})`,
                letterSpacing: "var(--v-track-tight)",
                textTransform: entry.label === "label" ? "uppercase" : undefined,
                fontWeight: entry.label === "display" ? 300 : 400,
              }}
            >
              {entry.sample}
            </span>
          </div>
        ))}
      </Section>

      <Section title="Radius">
        <div className={styles.radii}>
          {radii.map((token) => (
            <div key={token} className={styles.radius} style={{ borderRadius: `var(${token})` }}>
              {token.replace("--v-r-", "")}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Controls">
        <div className={styles.demo} style={{ marginBottom: "var(--v-s-5)" }}>
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost" icon="plus">
            Ghost
          </Button>
          <Button variant="quiet" icon="chevronRight" iconAfter>
            Quiet
          </Button>
          <IconButton icon="share" label="Share" />
          <IconButton icon="play" label="Start" tone="accent" />
        </div>
        <div className={styles.demo}>
          <Chip dot selected>
            Energise
          </Chip>
          <Chip dot>Recover</Chip>
          <Chip icon="moon">Sleep</Chip>
          <Badge>Even</Badge>
          <Badge tone="neutral" icon="clock">
            14 h
          </Badge>
          <SegmentedControl
            value="week"
            options={[
              { value: "day", label: "Day" },
              { value: "week", label: "Week" },
              { value: "year", label: "Year" },
            ]}
          />
        </div>
      </Section>

      <Section title="Data display">
        <div className={styles.gallery}>
          <Card>
            <CardHeader title="Stat sizes" subtitle="sm · md · lg" icon="chart" />
            <StatGroup divided>
              <Stat label="Energy" value="220" unit="kcal" size="sm" />
              <Stat label="Distance" value="10,58" unit="km" size="sm" />
            </StatGroup>
          </Card>

          <Card>
            <CardHeader
              title="Ring & delta"
              subtitle="Goal completion"
              icon="target"
              action={<ProgressRing value={68} size={48} />}
            />
            <div className={styles.demo}>
              <Delta value="2.4%" direction="up" />
              <Delta value="2 bpm" direction="down" invert />
              <Delta value="0.0" direction="flat" />
            </div>
          </Card>

          <Card>
            <CardHeader title="Bars" subtitle="accent · dim · muted" icon="pulse" />
            <BarSeries
              data={[40, 62, 55, 78, 66, 84, 71, { value: 38, tone: "dim" }, { value: 20, tone: "muted" }]}
              axis={["Mon", "Sun"]}
            />
          </Card>

          <Card>
            <CardHeader title="Sparkline" subtitle="Trend only" icon="bolt" />
            <Sparkline data={[58, 61, 57, 66, 70, 68, 74, 71, 79, 82]} />
          </Card>

          <Card>
            <CardHeader title="Rows" subtitle="With and without value" icon="grid" />
            <ListRow icon="moon" label="Sleep" meta="7 h 42 m" value="Good" href="#" />
            <ListRow icon="heart" label="Resting HR" meta="Down 2 bpm" value="48" />
          </Card>

          <Card variant="accent">
            <CardHeader title="Accent card" subtitle="One per screen, at most" icon="sparkle" />
            <Stat value="45" unit="min" caption="Reserved for the thing you want acted on." />
          </Card>
        </div>
      </Section>

      <Section title="Gauge">
        <ScoreGauge value={75} label="Vitals Score" rating={2} caption="Balanced" />
      </Section>

      <Section title="Icons">
        <div className={styles.icons}>
          {iconNames.map((name) => (
            <div key={name} className={styles.icon}>
              <Icon name={name} size={20} />
              <span>{name}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

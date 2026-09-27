import {
  AppShell,
  BottomNav,
  Card,
  CardHeader,
  Gutter,
  ListRow,
  Stack,
  ThemeToggle,
  TopBar,
} from "@/design";
import { Notice } from "@/app/components/Notice";
import { fetchCoach } from "@/app/lib/api";
import { navFor } from "@/app/lib/nav";
import prose from "@/app/components/Prose.module.css";
import styles from "./coach.module.css";

export const dynamic = "force-dynamic";

/**
 * The coach: what to do first, what your own data says, and what you are testing.
 *
 * The ranking is the part worth understanding. Every other coaching screen sorts by
 * how bad a number looks, which puts the same advice on top every day — your worst
 * line is your worst line. This sorts by how many points of your score are actually
 * recoverable, which is a different question and often has a different answer.
 *
 * Nothing on this page is written by a model, and nothing on it is arithmetic. The
 * points, the ranking, the zone boundaries and the experiment's verdict were all
 * computed in Python; this renders them.
 */
export default async function CoachPage() {
  const result = await fetchCoach();
  const nav = <BottomNav items={navFor("coach")} />;

  if (!result.ok) {
    return (
      <AppShell header={<TopBar title="Coach" centered />} nav={nav}>
        <Gutter>
          <Notice title="Can't reach the API" body={result.error} icon="pulse" />
        </Gutter>
      </AppShell>
    );
  }

  const { interventions, profile, experiment, caveat } = result.data;

  return (
    <AppShell
      header={<TopBar title="Coach" eyebrow="What to do next" right={<ThemeToggle />} />}
      nav={nav}
    >
      <Gutter>
        <Stack>
          {interventions.length === 0 ? (
            <Card>
              <CardHeader title="Nothing to chase today" icon="check" />
              <p className={prose.note}>
                Either there is no score yet, or nothing has enough points riding on it
                to be worth changing your day over. Both are fine answers — a coach
                that always has a demand is one you stop listening to.
              </p>
            </Card>
          ) : (
            <Card>
              <CardHeader title="Worth doing first" icon="target" />
              <p className={prose.note}>
                Ranked by the points your score could actually recover, not by which
                number looks worst.
              </p>
              <div>
                {interventions.map((item) => (
                  <article key={item.metric} className={styles.item}>
                    <div className={styles.head}>
                      <span className={styles.name}>{item.label}</span>
                      <span className={styles.worth}>{item.worth}</span>
                    </div>
                    <p className={styles.lever}>{item.lever}</p>
                    {item.evidence ? (
                      <p className={styles.evidence}>{item.evidence}</p>
                    ) : null}
                  </article>
                ))}
              </div>
            </Card>
          )}

          {experiment ? (
            <Card>
              <CardHeader title="What you're testing" icon="sparkle" />
              <p className={prose.note}>{experiment.hypothesis}</p>
              {experiment.conclusion ? (
                <p className={styles.lever}>{experiment.conclusion}</p>
              ) : null}
              {experiment.sample ? (
                <p className={styles.basis}>{experiment.sample}</p>
              ) : null}
              {experiment.days_left !== null ? (
                <p className={styles.basis}>
                  {experiment.days_left === 0
                    ? "The window closes today — the answer arrives with the next sync."
                    : `${experiment.days_left} days to go.`}
                </p>
              ) : null}
            </Card>
          ) : null}

          {profile.traits.length > 0 ? (
            <Card>
              <CardHeader title="Measured about you" icon="user" />
              {profile.traits.map((trait) => (
                <div key={trait.trait}>
                  <ListRow label={trait.label} value={trait.value} />
                  <p className={styles.basis}>{trait.basis}</p>
                </div>
              ))}
            </Card>
          ) : null}

          {profile.zones.length > 0 ? (
            <Card>
              <CardHeader title="Your heart-rate zones" icon="heart" />
              <p className={prose.note}>
                Against the highest heart rate your watch has actually recorded — not
                against 220 minus your age, which is a number that looks precise and
                is not.
              </p>
              <div className={styles.zones}>
                {profile.zones.map((zone) => (
                  <div key={zone.label} className={styles.zone}>
                    <span className={styles.zoneLabel}>{zone.label}</span>
                    <span className={styles.zoneBand}>{zone.band}</span>
                  </div>
                ))}
              </div>
            </Card>
          ) : null}

          <Card>
            <CardHeader title="The evidence" icon="chart" />
            <p className={prose.note}>
              What the analysis found in your own days — including how many things it
              tested to find it.
            </p>
            <ListRow label="Patterns" href="/insights" />
            <ListRow label="Ask about your data" href="/ask" />
          </Card>

          <Card>
            <CardHeader title="What this is not" icon="bolt" />
            <p className={styles.caveat}>{caveat}</p>
            <p className={styles.caveat}>
              Your pillar weights are not personalised, and deliberately so. Fitting
              them would need something to fit against, and the score is the weighted
              sum — there is no outcome to check it by. What is personalised is what
              the curves compare against, and which advice comes first.
            </p>
          </Card>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

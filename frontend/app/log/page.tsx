import {
  AppShell,
  BottomNav,
  Button,
  Card,
  CardHeader,
  Gutter,
  Stack,
  ThemeToggle,
  TopBar,
} from "@/design";
import { Notice } from "@/app/components/Notice";
import { saveDay } from "@/app/log/actions";
import { fetchAskSettings, fetchContext } from "@/app/lib/api";
import { longDate } from "@/app/lib/display";
import { navFor } from "@/app/lib/nav";
import prose from "@/app/components/Prose.module.css";
import field from "@/app/components/Field.module.css";
import styles from "./log.module.css";

export const dynamic = "force-dynamic";

type Search = Promise<{ day?: string }>;

/**
 * The day, in your words.
 *
 * Every other screen reports what a device measured. This one is the only place the
 * app asks a question, and it is built to be answered in about eight seconds: tick
 * what happened, done. Nothing here is required, and a day with nothing worth saying
 * is meant to be left alone rather than filled in with nine "no"s.
 *
 * Plain checkboxes and a form post — no client JavaScript. It has to work at 11pm on
 * a phone with one bar, and ticking boxes is something HTML has done natively for
 * thirty years.
 */
export default async function LogPage({ searchParams }: { searchParams: Search }) {
  const { day } = await searchParams;
  const [result, settings] = await Promise.all([fetchContext(day), fetchAskSettings()]);
  const sharing = settings.ok && settings.data.share_notes_with_ai;
  const nav = <BottomNav items={navFor("log")} />;

  if (!result.ok) {
    return (
      <AppShell header={<TopBar title="The day" centered />} nav={nav}>
        <Gutter>
          <Notice title="Can't reach the API" body={result.error} icon="pulse" />
        </Gutter>
      </AppShell>
    );
  }

  const context = result.data;
  const chosen = new Map(context.tags.map((tag) => [tag.name, tag.magnitude]));

  return (
    <AppShell
      header={
        <TopBar
          title="The day"
          eyebrow={longDate(context.date)}
          right={<ThemeToggle />}
        />
      }
      nav={nav}
    >
      <Gutter>
        <form action={saveDay}>
          <input type="hidden" name="day" value={day ?? ""} />
          <Stack>
            <Card>
              <CardHeader title="What happened?" icon="sparkle" />
              <p className={prose.note}>
                Tick anything that applies. This is the only thing your watch cannot
                tell the app, and it is what lets it explain the numbers rather than
                just report them. Nothing here changes your score.
              </p>

              <div className={styles.tags}>
                {context.vocabulary.map((tag) => {
                  const on = chosen.has(tag.name);
                  return (
                    <label key={tag.name} className={styles.tag}>
                      <input
                        type="checkbox"
                        name="tag"
                        value={tag.name}
                        defaultChecked={on}
                        className={styles.check}
                      />
                      <span className={styles.body}>
                        <span className={styles.label}>{tag.label}</span>
                        <span className={styles.hint}>{tag.hint}</span>
                      </span>
                      {tag.magnitude ? (
                        <input
                          type="number"
                          name={`magnitude:${tag.name}`}
                          defaultValue={chosen.get(tag.name) ?? ""}
                          min={0}
                          max={99}
                          inputMode="numeric"
                          aria-label={`${tag.label} — ${tag.magnitude}`}
                          placeholder={tag.magnitude}
                          className={styles.magnitude}
                        />
                      ) : null}
                    </label>
                  );
                })}
              </div>
            </Card>

            <Card>
              <CardHeader title="Anything else" icon="share" />
              <p className={prose.note}>
                For you, not for the app. This is never analysed, never correlated
                and never scored.
              </p>
              {/* The wording moves with the setting rather than staying reassuring
                  while the behaviour changes underneath it. Phase 9 made this text
                  conditional; leaving the original sentence in place would have made
                  it a lie for anyone who turned sharing on. */}
              <p className={prose.note}>
                {sharing
                  ? "You have allowed answers on the Ask screen to read these notes. Nothing else reads them."
                  : "It is never shown to a model. You can change that on the Ask screen."}
              </p>
              <textarea
                name="note"
                defaultValue={context.note ?? ""}
                rows={3}
                maxLength={2000}
                placeholder="Optional"
                className={`${field.input} ${styles.note}`}
              />
            </Card>

            <Button type="submit" block>
              Save the day
            </Button>
          </Stack>
        </form>
      </Gutter>
    </AppShell>
  );
}

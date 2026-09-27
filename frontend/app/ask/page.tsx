import {
  AppShell,
  BottomNav,
  Card,
  CardHeader,
  Gutter,
  Stack,
  ThemeToggle,
  TopBar,
} from "@/design";
import { Notice } from "@/app/components/Notice";
import { AskForm } from "./AskForm";
import { setNoteSharing } from "./actions";
import { fetchAskSettings } from "@/app/lib/api";
import { navFor } from "@/app/lib/nav";
import prose from "@/app/components/Prose.module.css";
import styles from "./ask.module.css";

export const dynamic = "force-dynamic";

const EXAMPLES = [
  "Why is my score down?",
  "How did I sleep this week?",
  "Have I had a day like this before?",
  "What should I do about my training?",
];

/**
 * Ask.
 *
 * The model is given a pack of facts assembled in Python from the words in the
 * question, and may state no number that is not in it. It never chooses what to
 * fetch — a model that picks its own retrieval can pick nothing and answer from
 * memory, which on health data is the failure that matters.
 *
 * The notes toggle lives here rather than in a settings screen because this is where
 * the decision has consequences, and because the Log screen made a promise about
 * those notes that a person should be able to find and change in one place.
 */
export default async function AskPage() {
  const settings = await fetchAskSettings();
  const nav = <BottomNav items={navFor("coach")} />;

  return (
    <AppShell
      header={<TopBar title="Ask" eyebrow="About your own days" right={<ThemeToggle />} />}
      nav={nav}
    >
      <Gutter>
        <Stack>
          <Card>
            <CardHeader title="Ask about your data" icon="sparkle" />
            <AskForm examples={EXAMPLES} />
          </Card>

          <Card>
            <CardHeader title="What it can and cannot do" icon="chart" />
            <p className={prose.note}>
              It answers from your own days and nothing else. It has no memory of you
              between questions, no general medical knowledge worth applying to your
              numbers, and every number it writes is checked against your data before
              you see it — an answer that invents one is thrown away and composed here
              instead.
            </p>
            <p className={prose.note}>
              It is not a doctor and it cannot diagnose anything.
            </p>
          </Card>

          {settings.ok ? (
            <Card>
              <CardHeader title="Your day notes" icon="moon" />
              <p className={prose.note}>{settings.data.explanation}</p>
              <form action={setNoteSharing}>
                <label className={styles.setting}>
                  <input
                    type="checkbox"
                    name="share"
                    defaultChecked={settings.data.share_notes_with_ai}
                    className={styles.check}
                  />
                  <span className={prose.note}>
                    Let answers read my day notes. They are still never analysed,
                    correlated or scored — only read, and only when you ask something.
                  </span>
                </label>
                <button type="submit" className={styles.example}>
                  Save
                </button>
              </form>
            </Card>
          ) : (
            <Notice title="Can't reach the API" body={settings.error} icon="pulse" />
          )}
        </Stack>
      </Gutter>
    </AppShell>
  );
}

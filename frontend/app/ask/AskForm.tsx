"use client";

import { useActionState } from "react";
import { Button } from "@/design";
import { ask, type AskState } from "./actions";
import field from "@/app/components/Field.module.css";
import styles from "./ask.module.css";

const EMPTY: AskState = { answer: null, error: null };

/**
 * The question field and its answer.
 *
 * A client component only because the answer has to appear without navigating away,
 * and because the pending state matters — a model takes a second or two and a button
 * that looks inert for two seconds gets pressed again.
 *
 * The answer's provenance is rendered here rather than left to the reader to infer.
 * An answer composed in Python because the model stated a number that was not in the
 * data must not look identical to one the model wrote and passed.
 */
export function AskForm({ examples }: { examples: string[] }) {
  const [state, action, pending] = useActionState(ask, EMPTY);
  const answer = state.answer;

  return (
    <>
      <form action={action} className={styles.form}>
        <textarea
          name="question"
          rows={2}
          maxLength={500}
          placeholder="Ask about your own days…"
          className={field.input}
          aria-label="Your question"
        />
        <Button type="submit" block disabled={pending}>
          {pending ? "Looking…" : "Ask"}
        </Button>
      </form>

      {state.error ? <p className={styles.provenance}>{state.error}</p> : null}

      {answer ? (
        <>
          {answer.written_by_model ? (
            <p className={styles.answer}>{answer.text}</p>
          ) : (
            <pre className={styles.facts}>{answer.text}</pre>
          )}
          <p className={styles.provenance}>
            {answer.written_by_model
              ? "Written by a model, from your data. Every number in it was checked against that data before you saw it."
              : "Composed here, from your data — no model wrote this."}
            {answer.note ? ` ${answer.note}.` : ""}
          </p>
        </>
      ) : (
        <div className={styles.examples}>
          {examples.map((text) => (
            <span key={text} className={styles.example}>
              {text}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

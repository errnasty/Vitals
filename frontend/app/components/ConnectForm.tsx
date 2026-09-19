"use client";

import { useActionState } from "react";
import { Button, Card, CardHeader } from "@/design";
import { submitAction, type ConnectState } from "@/app/connect/actions";
import styles from "./Field.module.css";
import prose from "./Prose.module.css";

/**
 * The two-step Garmin login: password, then the code.
 *
 * A client component because this is the one screen in the app with state a person
 * drives rather than state the database holds. The work still happens on the server
 * — the handler is a server action — so the password crosses the network once, to
 * our own origin, and the API token is never in the browser at all.
 *
 * Which step shows is whatever the server last said, never a local flag. The API is
 * what knows whether a login is waiting on a code; a form that disagreed with it
 * would offer a code box for a login that no longer exists.
 */
export function ConnectForm({ awaitingMfa }: { awaitingMfa: boolean }) {
  const [state, submit, pending] = useActionState<ConnectState, FormData>(
    submitAction,
    awaitingMfa
      ? { step: "code", message: "A login is already waiting for a code." }
      : { step: "password" },
  );

  if (state.step === "code") {
    return (
      <Card>
        <CardHeader title="Enter the code" icon="clock" />
        <p className={prose.note}>
          {state.message ?? "Garmin sent a code."} It is good for ten minutes.
        </p>
        {state.error ? <p className={prose.error}>{state.error}</p> : null}
        <form action={submit}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="code">
              Verification code
            </label>
            <input
              id="code"
              name="code"
              className={`${styles.input} ${styles.code}`}
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              required
            />
          </div>
          <Button type="submit" block disabled={pending}>
            {pending ? "Checking…" : "Finish connecting"}
          </Button>
        </form>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader title="Sign in to Garmin" icon="user" />
      <p className={prose.note}>
        Your Garmin Connect account — not your Vitals login. The password is used once
        to get a token, and is not kept afterwards.
      </p>
      {state.error ? <p className={prose.error}>{state.error}</p> : null}
      <form action={submit}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="email">
            Garmin email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            className={styles.input}
            autoComplete="username"
            inputMode="email"
            required
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="password">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            className={styles.input}
            autoComplete="current-password"
            required
          />
        </div>
        <Button type="submit" block disabled={pending}>
          {pending ? "Signing in…" : "Connect"}
        </Button>
      </form>
    </Card>
  );
}

"use server";

import { revalidatePath } from "next/cache";
import {
  postGarminConnect,
  postGarminDisconnect,
  postGarminMfa,
  postGarminSync,
} from "@/app/lib/api";

/**
 * The Connect screen's server actions.
 *
 * Server actions rather than a client-side fetch for the same reason every other
 * call in this app runs on the server: the API token lives in the web process's
 * environment and the browser never holds a credential. Here that matters twice
 * over — the Garmin password posts to *our* server and goes straight out to the
 * API, and at no point is it readable from client JavaScript.
 *
 * One action for both steps, dispatching on the step the server last reported.
 * Two actions with a hook each would give the form two opinions about which step
 * it is on, and the one place that must not happen is a login.
 */

export type ConnectState = {
  step: "password" | "code";
  error?: string;
  message?: string;
};

export async function submitAction(
  previous: ConnectState,
  form: FormData,
): Promise<ConnectState> {
  return previous.step === "code" ? submitCode(form) : submitPassword(form);
}

async function submitPassword(form: FormData): Promise<ConnectState> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");

  if (!email || !password) {
    return { step: "password", error: "Both fields are needed." };
  }

  const result = await postGarminConnect(email, password);
  if (!result.ok) {
    return { step: "password", error: result.error };
  }
  if (result.data.status === "mfa_required") {
    return { step: "code", message: result.data.detail };
  }
  return connected();
}

async function submitCode(form: FormData): Promise<ConnectState> {
  const code = String(form.get("code") ?? "").trim();
  if (!code) {
    return { step: "code", error: "Enter the code Garmin sent." };
  }

  const result = await postGarminMfa(code);
  if (!result.ok) {
    // A rejected code invalidates the half-finished login on the server, so there
    // is nothing left to retry against — back to the password.
    return { step: "password", error: `${result.error} Start again.` };
  }
  return connected();
}

function connected(): ConnectState {
  revalidatePath("/");
  revalidatePath("/connect");
  // No "connected" state of its own: Next re-renders the route after an action, so
  // the page re-reads /garmin/status and reports the result itself. A second copy
  // of that news in here would be a screen that could disagree with the server
  // about whether the login worked.
  return { step: "password" };
}

export async function syncAction(): Promise<void> {
  await postGarminSync();
  // The sync itself runs after the response, so there is nothing to wait for here.
  // Revalidating shows the connection's new state; the data lands a minute later.
  revalidatePath("/");
  revalidatePath("/connect");
}

export async function disconnectAction(): Promise<void> {
  await postGarminDisconnect();
  revalidatePath("/");
  revalidatePath("/connect");
}

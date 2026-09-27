"use server";

import { revalidatePath } from "next/cache";
import { postQuestion, putAskSettings } from "@/app/lib/api";
import type { AnswerView } from "@/app/lib/api";

/**
 * Asking, and changing who may read your notes.
 *
 * A plain form post, like the Log screen: the whole interaction is one text field
 * and a button, which HTML has done natively for thirty years, and the answer takes
 * a second or two to come back from a model anyway.
 */
export type AskState = { answer: AnswerView | null; error: string | null };

export async function ask(_previous: AskState, formData: FormData): Promise<AskState> {
  const question = String(formData.get("question") ?? "").trim();
  if (!question) {
    return { answer: null, error: null };
  }

  const result = await postQuestion(question);
  return result.ok
    ? { answer: result.data, error: null }
    : { answer: null, error: result.error };
}

export async function setNoteSharing(formData: FormData): Promise<void> {
  // A checkbox absent from the post is a checkbox that was unticked.
  await putAskSettings(formData.get("share") === "on");
  revalidatePath("/ask");
  revalidatePath("/log");
}

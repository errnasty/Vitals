"use server";

import { revalidatePath } from "next/cache";
import { putContextNote, putContextTags } from "@/app/lib/api";
import type { TagValue } from "@/app/lib/api";

/**
 * Saving a day's context.
 *
 * A plain form post, no client JavaScript. This screen has to work at 11pm on a
 * phone with one bar, and the whole interaction is ticking boxes — which HTML has
 * done natively for thirty years.
 */
export async function saveDay(formData: FormData): Promise<void> {
  const day = String(formData.get("day") ?? "") || undefined;

  // The form posts every ticked box, so what comes back *is* the day. Untouched
  // tags simply are not here, which is exactly what the API's replace expects.
  const tags: TagValue[] = formData
    .getAll("tag")
    .map((name) => String(name))
    .map((name) => {
      const raw = String(formData.get(`magnitude:${name}`) ?? "").trim();
      const parsed = Number.parseInt(raw, 10);
      return {
        name,
        magnitude: Number.isFinite(parsed) && parsed >= 0 ? parsed : null,
      };
    });

  await putContextTags(tags, day);

  const note = String(formData.get("note") ?? "");
  await putContextNote(note, day);

  revalidatePath("/log");
  revalidatePath("/");
}

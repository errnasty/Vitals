/**
 * The only place this app talks to the backend.
 *
 * Every call happens on the server, inside a React Server Component, and the token
 * lives in the web service's environment. The browser never holds a credential and
 * never makes a cross-origin request — which for a single-user app is both simpler
 * and stricter than shipping a token to the client and hoping.
 *
 * Nothing here transforms a number. The API sends values already formatted, because
 * the design system's contract is that components take formatted strings and the root
 * README's rule is that Python owns the arithmetic. This module's whole job is to
 * fetch, type and hand over.
 */

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const API_TOKEN = process.env.VITALS_API_TOKEN ?? "";

export type ScoreView = {
  value: number;
  display: string;
  coverage: string;
  trusted: boolean;
  rating: number;
  caption: string;
};

export type PillarView = {
  name: string;
  label: string;
  value: number;
  display: string;
  coverage: string;
};

export type HeadlineView = {
  key: string;
  label: string;
  value: string;
  meta: string | null;
};

export type BriefView = {
  date: string;
  body: string;
  source: string;
  written_by_model: boolean;
};

export type Today = {
  date: string | null;
  score: ScoreView | null;
  pillars: PillarView[];
  headlines: HeadlineView[];
  trend: number[];
  brief: BriefView | null;
  empty_reason: string | null;
};

export type ContributionView = {
  pillar: string;
  metric: string;
  label: string;
  value: string;
  points: string;
  points_value: number;
  effect: string;
  effect_value: number;
  coverage: string;
  rationale: string;
};

export type Explain = {
  date: string;
  score: ScoreView;
  pillars: PillarView[];
  contributions: ContributionView[];
};

export type SeriesPoint = { date: string; value: number };

export type SeriesView = {
  metric: string;
  label: string;
  latest: string;
  points: SeriesPoint[];
};

export type Trends = {
  days: number;
  score: SeriesPoint[];
  series: SeriesView[];
};

/** Either the payload, or a sentence a person can act on. */
export type Result<T> = { ok: true; data: T } | { ok: false; error: string };

async function get<T>(path: string): Promise<Result<T>> {
  if (!API_TOKEN) {
    return {
      ok: false,
      error: "No API token configured. Set VITALS_API_TOKEN on the web service.",
    };
  }

  try {
    const response = await fetch(`${API_URL}${path}`, {
      headers: { Authorization: `Bearer ${API_TOKEN}` },
      // Health data changes on a cron, and a stale dashboard is worse than a slow one.
      cache: "no-store",
    });

    if (response.status === 401) {
      return { ok: false, error: "The API rejected the token. Mint a new one." };
    }
    if (response.status === 403) {
      return { ok: false, error: "This account is not on the allowlist." };
    }
    if (response.status === 404) {
      return { ok: false, error: "Nothing recorded for that day yet." };
    }
    if (!response.ok) {
      return { ok: false, error: `The API returned ${response.status}.` };
    }

    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    // Almost always the api service asleep or the URL wrong, and saying so beats
    // a spinner that never resolves.
    return {
      ok: false,
      error: `Could not reach the API at ${API_URL} — ${
        error instanceof Error ? error.message : "unknown error"
      }`,
    };
  }
}

export const fetchToday = () => get<Today>("/today");
export const fetchExplain = (day?: string) =>
  get<Explain>(`/score/explain${day ? `?day=${day}` : ""}`);
export const fetchTrends = (days = 90) => get<Trends>(`/trends?days=${days}`);

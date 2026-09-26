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
  sync_warning: string | null;
  source_connected: boolean;
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

export type BackfillView = {
  running: boolean;
  done: boolean;
  /** Already a percentage string — Python does the arithmetic. */
  progress: string | null;
  since: string | null;
  reached: string | null;
  detail: string | null;
};

export type GarminStatus = {
  connected: boolean;
  state: string;
  needs_login: boolean;
  trouble: string | null;
  detail: string | null;
  awaiting_mfa: boolean;
  last_success_at: string | null;
  locked_until: string | null;
  history: BackfillView | null;
};

export type ConnectResult = {
  status: string;
  detail: string;
  display_name: string | null;
};

export type FactorView = {
  metric: string;
  label: string;
  rationale: string;
  value: string;
  points: string;
  points_value: number;
  coverage: string;
  effect: string;
  headroom: string;
  headroom_value: number;
  basis: string;
  target: string | null;
  scale: string | null;
  advice: string | null;
};

export type ReadingView = { label: string; value: string };

export type ReferenceView = {
  label: string;
  value: string;
  date: string;
  explanation: string;
};

export type PillarDetail = {
  name: string;
  label: string;
  display: string;
  value: number;
  coverage: string;
  trusted: boolean;
  weight: string;
  summary: string;
  factors: FactorView[];
  reference: ReferenceView | null;
  readings: ReadingView[];
};

export type PillarResponse = { date: string; pillar: PillarDetail };

export type PillarLink = {
  name: string;
  label: string;
  display: string;
  value: number;
  coverage: string;
  weight: string;
  summary: string;
};

export type ScoreDetail = {
  date: string;
  value: number;
  display: string;
  caption: string;
  coverage: string;
  trusted: boolean;
  method: { headline: string; steps: string[]; coverage_floor: string };
  pillars: PillarLink[];
  opportunities: FactorView[];
};

export type TagOption = {
  name: string;
  label: string;
  hint: string;
  icon: string;
  magnitude: string | null;
};

export type TagValue = { name: string; magnitude: number | null };

export type DayContext = {
  date: string;
  tags: TagValue[];
  note: string | null;
  vocabulary: TagOption[];
};

export type FindingView = {
  tag: string;
  tag_label: string;
  metric: string;
  /** The whole finding, numbers included, written in Python. Never assembled here. */
  sentence: string;
  when: string;
  change: string;
  direction: string;
  sample: string;
  confidence: string;
};

export type Insights = {
  findings: FindingView[];
  /** How many tests the run performed. Without it a finding cannot be read honestly. */
  tested: number;
  tagged_days: number;
  window_start: string | null;
  window_end: string | null;
  empty_reason: string | null;
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

/**
 * POST, for the two endpoints that change something.
 *
 * Separate from `get` because the failures differ: a 401 here means Garmin rejected
 * the credentials, not that our own token expired, and the API's own sentence is the
 * one worth showing. Read it out of the body rather than substituting a generic line.
 */
async function send<T>(method: string, path: string, body: unknown): Promise<Result<T>> {
  if (!API_TOKEN) {
    return {
      ok: false,
      error: "No API token configured. Set VITALS_API_TOKEN on the web service.",
    };
  }

  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${API_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    if (!response.ok) {
      const detail = await response
        .json()
        .then((payload: { detail?: string }) => payload.detail)
        .catch(() => undefined);
      return { ok: false, error: detail ?? `The API returned ${response.status}.` };
    }

    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    return {
      ok: false,
      error: `Could not reach the API at ${API_URL} — ${
        error instanceof Error ? error.message : "unknown error"
      }`,
    };
  }
}

const put = <T,>(path: string, body: unknown) => send<T>("PUT", path, body);

export const fetchToday = () => get<Today>("/today");
export const fetchContext = (day?: string) =>
  get<DayContext>(`/context${day ? `?day=${day}` : ""}`);
export const fetchScoreDetail = (day?: string) =>
  get<ScoreDetail>(`/score/detail${day ? `?day=${day}` : ""}`);
export const fetchPillar = (name: string, day?: string) =>
  get<PillarResponse>(`/score/pillar/${name}${day ? `?day=${day}` : ""}`);
const post = <T,>(path: string, body: unknown) => send<T>("POST", path, body);

export const fetchGarminStatus = () => get<GarminStatus>("/garmin/status");
export const postGarminConnect = (email: string, password: string) =>
  post<ConnectResult>("/garmin/connect", { email, password });
export const postGarminMfa = (code: string) =>
  post<ConnectResult>("/garmin/connect/mfa", { code });
export const postGarminDisconnect = () => post<GarminStatus>("/garmin/disconnect", {});
export const postGarminSync = () =>
  post<{ started: boolean; detail: string }>("/garmin/sync", {});
export const putContextTags = (tags: TagValue[], day?: string) =>
  put<DayContext>(`/context/tags${day ? `?day=${day}` : ""}`, { tags });
export const putContextNote = (note: string | null, day?: string) =>
  put<DayContext>(`/context/note${day ? `?day=${day}` : ""}`, { note });
export const fetchExplain = (day?: string) =>
  get<Explain>(`/score/explain${day ? `?day=${day}` : ""}`);
export const fetchTrends = (days = 90) => get<Trends>(`/trends?days=${days}`);
export const fetchInsights = () => get<Insights>("/insights");

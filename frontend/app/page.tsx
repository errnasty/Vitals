type HealthCheck = { ok: boolean; version?: string | null; error?: string };

type Health = {
  status: string;
  version: string;
  environment: string;
  git_sha: string | null;
  latency_ms: number;
  checks: Record<string, HealthCheck>;
};

const API_URL = process.env.API_URL ?? "http://localhost:8000";

async function fetchHealth(): Promise<Health | { error: string }> {
  try {
    const response = await fetch(`${API_URL}/healthz`, { cache: "no-store" });
    return (await response.json()) as Health;
  } catch (error) {
    return { error: error instanceof Error ? error.message : "unreachable" };
  }
}

// Phase 0 exists to prove one thing: web -> api -> database, deployed, end to end.
// This page is that proof, and nothing more; phase 6 replaces it with the Today view.
export default async function Page() {
  const health = await fetchHealth();
  const reachable = !("error" in health);

  return (
    <main>
      <h1>Vitals</h1>
      <p className="muted">Phase 0 — deployment skeleton.</p>

      <dl className="rows">
        <div className="row">
          <dt>api</dt>
          <dd className={reachable ? "ok" : "bad"}>
            {reachable ? health.status : `unreachable · ${health.error}`}
          </dd>
        </div>
        {reachable && (
          <>
            <div className="row">
              <dt>database</dt>
              <dd className={health.checks.database?.ok ? "ok" : "bad"}>
                {health.checks.database?.ok ? "connected" : "down"}
              </dd>
            </div>
            <div className="row">
              <dt>pgvector</dt>
              <dd className={health.checks.pgvector?.ok ? "ok" : "bad"}>
                {health.checks.pgvector?.ok ? `v${health.checks.pgvector.version}` : "missing"}
              </dd>
            </div>
            <div className="row">
              <dt>environment</dt>
              <dd>{health.environment}</dd>
            </div>
            <div className="row">
              <dt>version</dt>
              <dd>
                {health.version}
                {health.git_sha ? ` · ${health.git_sha.slice(0, 7)}` : ""}
              </dd>
            </div>
            <div className="row">
              <dt>round trip</dt>
              <dd>{health.latency_ms} ms</dd>
            </div>
          </>
        )}
      </dl>
    </main>
  );
}

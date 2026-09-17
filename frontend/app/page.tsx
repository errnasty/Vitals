import {
  AppShell,
  Badge,
  Card,
  Gutter,
  ListRow,
  Stack,
  Stat,
  ThemeToggle,
  TopBar,
} from "@/design";

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
// It is drawn with the design system so the proof and the product look like one app.
export default async function Page() {
  const health = await fetchHealth();
  const reachable = !("error" in health);

  return (
    <AppShell
      header={
        <TopBar
          title="Vitals"
          eyebrow="Phase 0 · skeleton"
          right={
            <>
              <Badge tone={reachable ? "accent" : "neutral"}>
                {reachable ? "live" : "down"}
              </Badge>
              <ThemeToggle />
            </>
          }
        />
      }
    >
      <Gutter>
        <Stack>
          <Card>
            <Stat
              label="Round trip"
              value={reachable ? health.latency_ms : "—"}
              unit={reachable ? "ms" : undefined}
              icon="bolt"
              accent={reachable}
              caption={
                reachable
                  ? `${health.environment} · ${health.version}${
                      health.git_sha ? ` · ${health.git_sha.slice(0, 7)}` : ""
                    }`
                  : `api unreachable · ${health.error}`
              }
            />
          </Card>

          <Card padding="sm">
            <ListRow icon="pulse" label="API" value={reachable ? health.status : "unreachable"} />
            {reachable ? (
              <>
                <ListRow
                  icon="grid"
                  label="Database"
                  value={health.checks.database?.ok ? "connected" : "down"}
                />
                <ListRow
                  icon="sparkle"
                  label="pgvector"
                  value={
                    health.checks.pgvector?.ok ? `v${health.checks.pgvector.version}` : "missing"
                  }
                />
              </>
            ) : null}
          </Card>

          <Card href="/design">
            <ListRow
              icon="chart"
              label="Design system"
              meta="Tokens, primitives and the reference screens"
              chevron
            />
          </Card>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

import { AppShell, Badge, BottomNav, Button, Card, CardHeader, Gutter, Stack, ThemeToggle, TopBar } from "@/design";
import { ConnectForm } from "@/app/components/ConnectForm";
import { Notice } from "@/app/components/Notice";
import { disconnectAction, syncAction } from "@/app/connect/actions";
import { fetchGarminStatus } from "@/app/lib/api";
import { navFor } from "@/app/lib/nav";
import prose from "@/app/components/Prose.module.css";

export const dynamic = "force-dynamic";

/**
 * Connect — the one screen where the app writes rather than reads.
 *
 * `vitals garmin login` is still the better way to do this, and the screen says so
 * rather than hiding it: Garmin's SSO is behind Cloudflare, this request leaves a
 * datacenter, and the person deserves to know that before they type a password.
 * The screen exists because a connector you cannot connect from the device you have
 * on you is not much of a connector.
 */
export default async function Page() {
  const result = await fetchGarminStatus();

  const header = <TopBar title="Connect" eyebrow="Garmin" right={<ThemeToggle />} />;
  const nav = <BottomNav items={navFor("")} />;

  if (!result.ok) {
    return (
      <AppShell header={header} nav={nav}>
        <Gutter>
          <Notice title="Can't reach the API" body={result.error} icon="pulse" />
        </Gutter>
      </AppShell>
    );
  }

  const status = result.data;

  // Connected means "we hold usable tokens", not "the last run went well". A sync
  // that backed off must not put the login form back in front of someone — signing
  // in again is a fresh SSO attempt from a datacenter, which is the one thing worth
  // avoiding here.
  if (status.connected && !status.needs_login) {
    return (
      <AppShell header={header} nav={nav}>
        <Gutter>
          <Stack>
            <Card>
              <CardHeader
                title="Garmin is connected"
                icon="check"
                action={
                  <Badge
                    tone={
                      status.trouble || (status.history && !status.history.done)
                        ? "neutral"
                        : "accent"
                    }
                  >
                    {status.history && !status.history.done
                      ? status.history.progress
                      : status.trouble
                        ? "Retrying"
                        : "Active"}
                  </Badge>
                }
              />
              {status.trouble ? <p className={prose.note}>{status.trouble}</p> : null}
              <p className={prose.note}>
                The sync runs every six hours and fills in from today backwards.
                Tokens last about a year and refresh themselves, so this should not
                need touching again.
              </p>
              {status.history ? (
                <p className={prose.note}>
                  {status.history.done
                    ? `Your history is in, back to ${status.history.since}.`
                    : `Pulling your history — ${status.history.progress} of the way back to ${status.history.since}. It carries on in the background and resumes on the next sync, so you can close the app.`}
                  {status.history.detail ? ` ${status.history.detail}` : ""}
                </p>
              ) : null}
            </Card>
            <form action={syncAction}>
              <Button type="submit" block>
                Sync now
              </Button>
            </form>

            <form action={disconnectAction}>
              <Button type="submit" variant="quiet" block>
                Disconnect
              </Button>
            </form>
          </Stack>
        </Gutter>
      </AppShell>
    );
  }

  return (
    <AppShell header={header} nav={nav}>
      <Gutter>
        <Stack>
          {status.trouble ? (
            <Notice title="Signing in again" body={status.trouble} icon="bolt" />
          ) : null}
          <ConnectForm awaitingMfa={status.awaiting_mfa} />
          <Card variant="flat" padding="sm">
            <CardHeader title="Worth knowing" icon="bolt" />
            <p className={prose.note}>
              Garmin&rsquo;s sign-in is behind Cloudflare, which is stricter with
              requests from a datacenter than from a home connection — and this one
              comes from the server. It usually works, and repeated failures are what
              risk locking an account, so the app stops you after a few. Signing in
              with <code>vitals garmin login</code> from a computer avoids that
              entirely, and only needs doing about once a year.
            </p>
          </Card>
        </Stack>
      </Gutter>
    </AppShell>
  );
}

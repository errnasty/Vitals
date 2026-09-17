# Authentication — phase 1

A public URL is the reason this phase comes before any health data exists. Everything
below the health endpoints is closed by default: no token, no data.

## How it works

This deployment is its own identity provider. `vitals auth token` signs an HS256 JWT
with `VITALS_AUTH_JWT_SECRET`; the API verifies the signature and the claims locally on
every request. No provider to sign up for, nothing to pause after a week of inactivity,
nothing on the request path that can be down.

```
you ──vitals auth token──> a JWT in your password manager
browser/curl ──Authorization: Bearer <JWT>──> api ──verify locally──> app_user row
```

An external OIDC provider drops into the same slot. Set `VITALS_AUTH_ISSUER` and
`VITALS_AUTH_JWKS_URL` and tokens are verified against its published keys instead;
`vitals auth token` then refuses to mint, because the provider is the only party
entitled to sign its own `iss`.

| Mode | Algorithm | Key material | Config |
|---|---|---|---|
| self-issued | HS256 | one shared secret | `VITALS_AUTH_JWT_SECRET` |
| external | ES256/RS256 | the provider's published JWKS, cached and rotated | `VITALS_AUTH_ISSUER` + `VITALS_AUTH_JWKS_URL` |

A token selects which *path* runs by its own header's `alg`, but never the algorithm a
key is verified with: the HMAC path only ever uses the shared secret, and the asymmetric
path only ever uses a JWKS key with that key's own declared algorithm. That closes the
classic algorithm-confusion attack, where a token is signed with HS256 using the
*public* key the attacker can also read, and a verifier that trusts the header accepts
it. Both attacks are in the test suite (`tests/test_auth_jwks.py`).

A token is accepted only if it is signed by a key we trust **and** carries the
configured `iss`, `aud` = `authenticated`, an unexpired `exp`, and a UUID `sub`.
Machine keys and anonymous sessions are rejected: they are authentic tokens, but they
are not you.

> Legacy: `SUPABASE_URL` and `SUPABASE_JWT_SECRET` are still read and still configure
> the external and HS256 paths respectively, so an existing `.env` keeps working.
> `vitals doctor` names them and points at the rename.

## The gates

1. **`VITALS_ALLOWED_EMAILS`** — checked on every request. With self-issued tokens this
   is the whole membership list, and `vitals auth token` refuses to mint for an address
   that is not on it rather than hand you a token every request would 403.
2. **`assert_auth_ready()`** in the app factory: outside `local`, the API **refuses to
   start** if no verification method is configured, if the allowlist is empty, or if
   auth is switched off. A failed deploy is a much better outcome than a successful one
   that serves your health history to the internet.

Behind an external provider, disable its public sign-ups too — but the allowlist is the
gate that does not depend on a dashboard toggle staying where you left it.

## Keeping the secret safe

The secret verifies tokens *and* signs them, so anyone holding it can mint a token for
any allowlisted address. It lives in Railway's environment and your password manager,
and nowhere else. Rotating it invalidates every outstanding token, which is exactly what
you want if one leaks: change the variable, redeploy, mint a new one.

This is a deliberate trade for a single-user prototype. An external provider splits that
capability in two — it holds a private key you never see, and this API only ever holds
the public half. When the app has users other than you, that is the upgrade, and it is
two environment variables rather than a refactor.

## Error contract

| Status | `error` | Meaning | What the frontend should do |
|---|---|---|---|
| 401 | `missing_credentials` | no `Authorization: Bearer` header | sign in |
| 401 | `invalid_token` | signature, issuer, audience or claims rejected | sign in |
| 401 | `token_expired` | otherwise valid, past `exp` | mint or refresh, retry once |
| 403 | `forbidden` | authentic token, not allowlisted or account disabled | show "not permitted", do not retry |
| 503 | `auth_unavailable` | JWKS unreachable with a cold cache, or nothing configured | retry with backoff, keep the session |

401s carry `WWW-Authenticate: Bearer realm="vitals", error="<code>"`. The 401/503 split
matters: a provider outage must not look like a bad credential and log you out of the
app that is still perfectly able to serve your data. Self-issued tokens cannot produce
503 at all — there is nothing to be unreachable.

JWKS handling is built for the outage rather than the happy path: keys are cached with a
TTL, an unknown `kid` triggers at most one cooldown-gated refetch (so a forged `kid`
cannot be used to hammer the provider), a failed refresh with a warm cache keeps serving
the cached keys, and only a cold cache produces 503.

## Endpoints

| Route | Auth | Notes |
|---|---|---|
| `GET /livez` | public | Railway's healthcheck. Never touches the database or auth |
| `GET /healthz` | public | database reachability, and whether pgvector is present |
| `GET /auth/me` | required | the `app_user` row plus what the presented token proved |

Every route added from phase 2 on depends on `CurrentUserDep`, which is also what
provisions the local user. There are two identity dependencies:

- `CurrentPrincipalDep` — the verified token. No database involved.
- `CurrentUserDep` — the `app_user` row, created on first authenticated request.

`app_user.id` **is** the token's `sub` claim, and deliberately not a foreign key into
any provider's user table: every later table hangs off `app_user.id`, and phase 12
(multi-user) or a change of identity provider should not mean rewriting those
constraints. For a self-issued token the `sub` is a uuid5 of your address, so re-minting
keeps the same row. `app_user.is_active` is a local kill switch that works whatever the
issuer thinks.

## Running it

```bash
export VITALS_AUTH_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export VITALS_ALLOWED_EMAILS=you@example.com

uv run vitals auth token --email you@example.com --days 90   # prints a token
uv run vitals auth verify "$TOKEN"                            # what the API would decide
curl -H "Authorization: Bearer $TOKEN" localhost:8000/auth/me
```

The same commands work against the deployed API — point them at the same secret Railway
holds. `VITALS_AUTH_DISABLED=true` switches auth off entirely for local UI work; it is
local-only, and the app refuses to start with it set anywhere else.

## What is still open

- **Sign-in UI** — the dashboard lands in phase 6. Until then a token in a header is the
  whole login. The contract is already fixed: send `Authorization: Bearer <token>` and
  treat the table above as the state machine.
- **A real provider** — worth it when the app has users other than you, or when you want
  a magic link instead of a pasted token. Two variables, no code change.

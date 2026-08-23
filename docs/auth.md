# Authentication — phase 1

A public URL is the reason this phase comes before any health data exists. Everything
below the health endpoints is closed by default: no token, no data.

## How it works

Supabase Auth issues the token (email magic link); this API only ever **verifies** it.
Verification is a signature check plus claim validation against local key material —
there is no callback into Supabase on the request path, so the API keeps serving while
Supabase Auth is unreachable, and an authenticated request costs no network round trip.

```
browser ──magic link──> Supabase Auth ──JWT──> browser
browser ──Authorization: Bearer <JWT>──> api ──verify locally──> app_user row
```

Supabase signs tokens one of two ways and both are supported, chosen per token by its
header:

| Project | Algorithm | Key material | Config |
|---|---|---|---|
| current | ES256 (asymmetric) | published JWKS, cached and rotated | `SUPABASE_URL` |
| legacy | HS256 | shared project secret | `SUPABASE_JWT_SECRET` |

The header's `alg` selects which *path* runs, never the algorithm a key is verified
with: the HMAC path only ever uses the shared secret, and the asymmetric path only ever
uses a JWKS key with that key's own declared algorithm. That closes the classic
algorithm-confusion attack, where a token is signed with HS256 using the *public* key
the attacker can also read, and a verifier that trusts the header accepts it. Both
attacks are in the test suite (`tests/test_auth_jwks.py`).

A token is accepted only if it is signed by a key we trust **and** carries
`iss` = `{SUPABASE_URL}/auth/v1`, `aud` = `authenticated`, an unexpired `exp`, and a
UUID `sub`. Service-role keys and anonymous sessions are rejected: they are authentic
tokens, but they are not you.

## The two gates

1. **Supabase sign-ups disabled**, with only your address allowlisted in the dashboard.
2. **`VITALS_ALLOWED_EMAILS`** — checked on every request, independently of the first.

Two gates because the failure mode of the first silently regressing (a dashboard toggle
flipped, a project restored from a template) is a public health app anyone can sign up
to. The second gate is in this repository, reviewable, and covered by tests.

Backing them up, `assert_auth_ready()` runs in the app factory: outside `local`, the API
**refuses to start** if no verification method is configured, if the allowlist is empty,
or if auth is switched off. A failed deploy is a much better outcome than a successful
one that serves your health history to the internet.

## Error contract

| Status | `error` | Meaning | What the frontend should do |
|---|---|---|---|
| 401 | `missing_credentials` | no `Authorization: Bearer` header | sign in |
| 401 | `invalid_token` | signature, issuer, audience or claims rejected | sign in |
| 401 | `token_expired` | otherwise valid, past `exp` | refresh the session, retry once |
| 403 | `forbidden` | authentic token, not allowlisted or account disabled | show "not permitted", do not retry |
| 503 | `auth_unavailable` | JWKS unreachable with a cold cache, or nothing configured | retry with backoff, keep the session |

401s carry `WWW-Authenticate: Bearer realm="vitals", error="<code>"`. The 401/503 split
matters: an outage at Supabase must not look like a bad credential and log you out of
the app that is still perfectly able to serve your data.

JWKS handling is built for the outage rather than the happy path: keys are cached with a
TTL, an unknown `kid` triggers at most one cooldown-gated refetch (so a forged `kid`
cannot be used to hammer Supabase), a failed refresh with a warm cache keeps serving the
cached keys, and only a cold cache produces 503.

## Endpoints

| Route | Auth | Notes |
|---|---|---|
| `GET /livez` | public | Railway's healthcheck. Never touches the database or auth |
| `GET /healthz` | public | database + pgvector reachability |
| `GET /auth/me` | required | the `app_user` row plus what the presented token proved |

Every route added from phase 2 on depends on `CurrentUserDep`, which is also what
provisions the local user. There are two identity dependencies:

- `CurrentPrincipalDep` — the verified token. No database involved.
- `CurrentUserDep` — the `app_user` row, created on first authenticated request.

`app_user.id` **is** the Supabase `sub` claim, but it is deliberately not a foreign key
into `auth.users`: every later table hangs off `app_user.id`, and phase 12 (multi-user)
or a change of identity provider should not mean rewriting those constraints.
`app_user.is_active` is a local kill switch that works even when Supabase does not.

## Local development, with no Supabase project

The whole auth layer is exercisable offline. `vitals auth token` mints a real HS256 JWT
carrying exactly the claims Supabase issues, verified by exactly the same code path as a
production token — the only difference is who signed it.

```bash
export SUPABASE_JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export VITALS_ALLOWED_EMAILS=you@example.com

uv run vitals auth token --email you@example.com          # prints a token
uv run vitals auth verify "$TOKEN"                        # what the API would decide
curl -H "Authorization: Bearer $TOKEN" localhost:8000/auth/me
```

Minting is refused outside `ENVIRONMENT=local`, so there is no way to issue one on
Railway. `VITALS_AUTH_DISABLED=true` switches auth off entirely for local UI work; it is
also local-only, and the app refuses to start with it set anywhere else.

## What is still open

Verification is complete and tested; two things need the live project:

- **Supabase project** — create it, disable sign-ups, allowlist your address, then set
  `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_JWT_SECRET` on Railway.
  `vitals doctor` fetches the JWKS endpoint and reports the key set, which is the
  fastest way to confirm the project half is right.
- **Sign-in UI** — the magic-link flow lands with the dashboard in phase 6. The contract
  is already fixed: get the session from `supabase-js`, send
  `Authorization: Bearer <access_token>`, and treat the table above as the state machine.

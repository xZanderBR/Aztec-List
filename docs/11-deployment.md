# Deployment

How Aztec List runs as a public portfolio **sandbox demo**: always on, on a custom
domain, for about $4 a month or less. Visitors log in as seeded demo personas (no
signup, no email), the data resets on a schedule, and the AI features stay on.

## Architecture

```
Browser ── https://azteclist.<domain> ──► Vercel Hobby (Next.js 16, client-rendered)
   └──── https/wss://api.azteclist.<domain> ──► Fly.io, 1× shared-cpu-1x 512 MB, iad, always-on
                                                  ├─ volume /data (1 GB): SQLite DB, uploads/, qdrant/
                                                  ├─► Cloudflare Workers AI  @cf/baai/bge-small-en-v1.5 (embeddings)
                                                  └─► Anthropic API  Claude Haiku 5.5 (assistant, query expansion, descriptions)
```

| Concern | Service | Why |
| --- | --- | --- |
| Frontend | Vercel Hobby | First-class Next.js host, free for personal projects, preview deploys |
| Backend | Fly.io | Always-on container (no cold start), native WebSockets, persistent volume |
| Database | SQLite on the Fly volume | The app is single-instance by design; no external DB quota to exhaust; trivial resets |
| Vector store | Embedded Qdrant on the volume | Same code path as local dev; demo-scale data |
| Embeddings | Cloudflare Workers AI | Same BGE model as local fastembed, no ~1 GB ONNX runtime on the server |
| LLM | Anthropic, Claude Haiku 5.5 | Cheapest current Claude; `effort: low` |
| Error tracking | Sentry (optional) | Gated on `SENTRY__DSN` |

**Why one machine.** WebSocket fan-out, the rate limiter, and embedded Qdrant all keep
state in the process, and uploads live on local disk. So the backend runs exactly one
process on one machine (`--workers 1`, `WEB_CONCURRENCY=1`). Scaling out would need
Redis pub/sub, object storage (R2), and Postgres. That is deliberately deferred.

**Why SQLite here.** Postgres stays the docker-compose and dev default. For a
single-machine demo, SQLite on the volume is simpler and has no free-tier compute
quota to run out. The engine enables WAL mode, a busy timeout and foreign keys
(`app/core/database.py`). Migrations are the same Alembic revisions either way.

## Cost

| Item | Monthly |
| --- | --- |
| Fly shared-cpu-1x 512 MB, always-on (iad) | $3.69 list |
| Fly 1 GB volume | $0.15 |
| Fly certificates, shared IPv4 | $0 |
| Vercel Hobby | $0 |
| Workers AI (10k free neurons/day ≈ 5M embedding tokens/day) | $0 |
| Anthropic (dedicated workspace with a hard monthly spend limit) | ≤ the limit you set |

Fly currently waives personal-organization bills under $5, so the likely Fly charge is
$0. If the Anthropic limit is hit, the assistant replies "The demo's AI budget is used
up for this month" and smart search falls back to the raw query.

## How the container starts

`backend/Dockerfile` is multi-stage. It installs runtime dependencies only
(`uv sync --no-default-groups` skips dev tools and the `local-ai` fastembed group) and
runs as the non-root `app` user. `backend/docker-entrypoint.sh`:

1. Starts as root, creates `/data/uploads` and `/data/qdrant`, and `chown`s `/data`.
   Fly volumes mount root-owned.
2. Drops to `app` with `setpriv`.
3. In production, runs `alembic upgrade head`. This can't be a Fly `release_command`,
   because release machines don't mount volumes.
4. Starts `uvicorn` with one worker.

Production refuses to boot when any of these is true (`app/core/settings.py`):
- the JWT secret is still the placeholder
- `TEST__TEST_MODE` is on
- the CORS origins include localhost

Rate limits key on Fly's `Fly-Client-IP` header (`app/core/rate_limiter.py`), so each
visitor gets their own bucket behind the proxy.

## Demo mode

`DEMO__ENABLED=true` (set in `fly.toml`) turns the deployment into a sandbox:

- **Seed data.** On first boot the API seeds `backend/src/app/demo/seed_data.json`:
  - three login personas (a seller, a buyer, a moderator)
  - background students
  - 33 listings
  - conversations, a pending scam report, a flagged listing and support tickets

  Listing photos are generated placeholders. To use real photos, drop files into
  `backend/src/app/demo/photos/` (see the README there).
- **Login.** Visitors log in with `POST /api/v1/auth/demo/{persona}`. There is no
  password, signup or email. `GET /api/v1/config` lists the personas and the next reset
  time for the frontend.
- **Resets.** Everything resets to the seed every `DEMO__RESET_INTERVAL_HOURS` (default
  6, aligned to UTC). Seeded rows keep fixed IDs, so persona sessions and listing URLs
  survive resets.
- **Blocked actions.** Signup, email, username and password changes, and account or
  profile deletion return 403 "Disabled in the demo". The moderator can strike or ban
  background students but not the login personas.
- **AI limits.** AI routes are limited to 5 requests per minute and 30 per day per IP.

Never enable demo mode on a deployment with real users: every reset deletes all rows.

## One-time setup

### 1. Accounts and keys (you)

- **Fly.io:** create an account and add a card. Install `flyctl` and run `fly auth login`.
- **Cloudflare:** create a free account. Create an API token with the **Workers AI: Read**
  permission and note your account ID.
- **Anthropic:**
  1. In the Console, create a workspace (e.g. `aztec-list-demo`).
  2. Set its monthly **spend limit** (for example $1).
  3. Create an API key in that workspace.

  The workspace limit is a hard cap. At the limit the API rejects requests instead of
  billing. The default workspace can't have its own limit.
- **Vercel:** sign in with GitHub.

### 2. Check the embedding parity (optional, recommended)

Run this from `backend/` with the Cloudflare credentials. It confirms the hosted model
matches the local fastembed vectors that the search tuning was done with (see
`docs/06-semantic-search.md`):

```bash
EMBEDDING__CLOUDFLARE_ACCOUNT_ID=... EMBEDDING__CLOUDFLARE_API_TOKEN=... uv run python scripts/compare_embeddings.py
```

### 3. Backend on Fly.io

In `backend/fly.toml`, replace `azteclist.example.com` with your frontend domain. Then,
from `backend/`:

```bash
fly launch --no-deploy --copy-config      # creates the app from fly.toml
```

```bash
fly volumes create data --size 1 --region iad
```

```bash
fly secrets set JWT__SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  LLM__ANTHROPIC_API_KEY=... \
  EMBEDDING__CLOUDFLARE_ACCOUNT_ID=... \
  EMBEDDING__CLOUDFLARE_API_TOKEN=...
```

```bash
fly deploy
```

```bash
fly certs add api.azteclist.<domain>
```

Optional: `fly secrets set SENTRY__DSN=...`.

### 4. Frontend on Vercel

Import `xZanderBR/aztec-list` and set the root directory to `frontend`. Set these
environment variables. They are inlined at build time, so redeploy after changing them:

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.azteclist.<domain>/api/v1` |
| `NEXT_PUBLIC_STATIC_BASE_URL` | `https://api.azteclist.<domain>` |

WebSocket URLs are derived from `NEXT_PUBLIC_API_BASE_URL`, so `https` becomes `wss`.
Add the domain `azteclist.<domain>` in the project settings.

### 5. DNS

| Record | Name | Target |
| --- | --- | --- |
| CNAME | `azteclist` | `cname.vercel-dns.com` |
| CNAME | `api.azteclist` | `aztec-list-api.fly.dev` |

Both platforms issue TLS certificates automatically once DNS resolves. On Cloudflare
DNS, set both records to **DNS only** (grey cloud) so the platforms can issue their
certificates.

### 6. Continuous deployment

- **Backend:** `.github/workflows/deploy.yml` deploys to Fly after the Tests workflow
  passes on `main`. Create a deploy token and add it as the `FLY_API_TOKEN` repository
  secret:

  ```bash
  fly tokens create deploy --app aztec-list-api
  ```

  Until the secret exists, the workflow skips.
- **Frontend:** Vercel deploys `main` and builds previews for pull requests
  automatically.

### 7. Monitoring

- Fly checks `/health` (liveness) and `/ready` (database and vector store).
- Add a free uptime monitor (for example UptimeRobot) on `https://api.azteclist.<domain>/ready`
  and on the site.
- `fly logs` streams JSON logs.

## Operations

Show logs and machine state:

```bash
fly logs
```

```bash
fly status
```

Reset the demo to its seed now. This also rebuilds the vector index. It needs the
`DEMO__RESET_TOKEN` secret:

```bash
fly secrets set DEMO__RESET_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

```bash
fly ssh console -C "python scripts/reset_demo.py"
```

Don't run `scripts/reindex_listings.py` on the live machine. The embedded Qdrant index
is single-process, and the running server holds its lock.

Shell into the machine:

```bash
fly ssh console
```

Size check: the production image has no ONNX runtime. If memory ever runs tight, the
machine has 512 MB of swap (`swap_size_mb` in `fly.toml`) before anything is killed.

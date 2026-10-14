# cs2-market-analysis

A dashboard to visualise CSFloat and Skinport market data

See [plan/cs2-market-analysis-plan.md](plan/cs2-market-analysis-plan.md) for the full design.

## Local dev setup

Everything runs in Docker, so the only requirements are Docker Desktop (Compose v2.24+)
a CSFloat API key and a Skinport API client id/secret. `uv` is only needed to run scripts or tests outside Docker.

### macOS

```bash
git clone <repo-url> && cd cs2-market-analysis
cp .env.example .env      # fill in CSFLOAT_API_KEY, SKINPORT_ID, SKINPORT_SECRET
docker compose up -d --build
```

### Windows

Use Docker Desktop with the WSL 2 backend, and clone the repo **inside WSL** (e.g.
`~/code` in Ubuntu), not on `C:\`. On a Windows-drive checkout, file changes often
don't reach the containers, so the dashboard won't hot-reload, and file access is much slower.

```bash
# in a WSL (Ubuntu) terminal
git clone <repo-url> && cd cs2-market-analysis
cp .env.example .env      # fill in CSFLOAT_API_KEY, SKINPORT_ID, SKINPORT_SECRET
docker compose up -d --build
```

From then on every command in this README works unchanged in that WSL terminal. To
edit the code, run `code .` from WSL, which opens VS Code connected to WSL.

If you do run from PowerShell on a Windows-drive checkout instead, the Docker commands
are the same; only the copy step differs: `Copy-Item .env.example .env`.

### What's running

That runs everything: Postgres (host port 5433), Redpanda (Kafka-API compatible, 9092),
migrations (one-shot), the CSFloat and Skinport ingesters, the consolidator, the analysis scheduler,
the API (<http://localhost:8000>) and the dashboard (<http://localhost:3000>).

```bash
docker compose logs -f consolidator     # follow one service
docker compose up -d --build api        # rebuild after Python code changes
docker compose stop ingestion-csfloat   # stop one service
```

All Python services share one image (`Dockerfile`). Inside the compose network they
reach Postgres/Redpanda by service name; those overrides live in `docker-compose.yml`,
so `.env` keeps the `localhost` values for running a script on the host instead —
stop its container first, then e.g.:

```bash
uv run pytest                        # unit + integration tests (needs postgres up; each test rolls back)
uv run python -m ingestion.skinport  # polls Skinport every SKINPORT_POLL_INTERVAL_SECONDS
uv run python -m analysis            # one-shot: trend, volatility, arbitrage, underpriced_listing
uv run uvicorn api.main:app --reload
```

`DB_PORT` is `5433` in `.env.example`, not the standard `5432`, to avoid colliding with any
pre-existing local Postgres install.

### Dashboard (no local Node needed)

Node isn't required on the host — the `dashboard` service runs `next dev` inside a
`node:22-alpine` container with `dashboard/` mounted in, installing its own Linux
`node_modules` into a named volume. Its server-side fetches use `API_BASE_URL=http://api:8000`
(set in `docker-compose.yml`); the browser uses `NEXT_PUBLIC_API_BASE_URL`, defaulting to
`http://localhost:8000`.

To add an npm package (works the same on macOS and Windows):

```bash
docker compose exec dashboard npm install <package>
```

## Layout

- `db/` — SQLAlchemy models (source of truth for the schema) + session factory, shared by everything below
- `migrations/` — Alembic migrations, generated from `db/models.py`
- `ingestion/` — per-marketplace polling plugins (`ingestion/common` holds the shared plugin interface). `ingestion/skinport` publishes Skinport's per-item lowest ask + stock count (its API has no individual listings or floats), skipping StatTrak™/Souvenir
- `consolidator/` — single Kafka consumer: dedups, upserts `listings`/`skin_variants`, appends `price_history`, expires listings nobody has re-observed
- `analysis/` — scheduled batch modules (`trend.py`, `arbitrage.py`, `underpriced.py`) — read Postgres only, no Kafka dependency
- `api/` — FastAPI service serving `analysis_results` and listing browse/filter queries
- `dashboard/` — Next.js frontend

## Keeping listings current

Listings change after we first see them: prices move, items sell, sellers pull them.
Each `listings` row has a `status` (`active`, `sold`, `delisted` or `expired`) and a
`removed_at` time. Analysis and the API only use `active` rows. Removed rows are kept
with their last known price rather than deleted.

**How changes are detected**

- **CSFloat**: the `most_recent` feed only shows a listing while it's new, so the
  ingester tracks every listing it has seen. Each poll it also rechecks the
  `CSFLOAT_RECHECK_PER_POLL` (default 20) listings that were checked longest ago, via
  `GET /v1/listings/{id}`. That endpoint returns `state` as `listed`, `sold` or
  `delisted`, and the current price. Rechecks pause when the by-id rate limit runs low.
- **Skinport**: each poll returns the full catalog of per-item lowest asks. The ingester
  sends items whose price or stock changed, items that disappeared (as `delisted`), and
  every unchanged item once every `SKINPORT_RECONFIRM_HOURS` (default 6). Skinport
  doesn't say whether units sold or were pulled, so it never reports `sold`.

**What the consolidator does with an observation**

| Observation | `listings` row | `price_history` |
| --- | --- | --- |
| New listing, or relisted after sold/delisted | `active` | `listed` point |
| Seen again, price changed | `active`, new price | `listed` point |
| Seen again, same price | `last_updated` refreshed | nothing |
| Sold | `sold`, keeps price | `sold` point (once) |
| Delisted | `delisted`, keeps price | nothing |

Only writing a price point when something changed stops long-lived listings (and
ingester restarts) from flooding the trend and underpriced baselines with duplicates.

**Expiry backstop**: ingesters track listings in memory, so a restart forgets them.
Every 10 minutes the consolidator marks `active` listings that haven't been observed for
`LISTING_STALE_AFTER_HOURS` (default 48) as `expired`. If an expired listing is seen
again, it goes back to `active` without a new price point.

**Analysis results**: arbitrage and underpriced results describe the market right now,
so `/analysis` only returns those from the newest run. A listing that sold since an
earlier run no longer shows up as a signal.

**Known limits**

- CSFloat's by-id endpoint allows about 50k requests a day, fewer than the number of
  new listings, so many CSFloat listings leave `active` by expiring rather than being
  caught as sold or delisted.
- The CSFloat feed has its own limit of 200 requests per window. Polling 5 pages a
  minute runs past it, so the ingester periodically pauses until the window resets.

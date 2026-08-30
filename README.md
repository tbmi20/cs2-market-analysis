# cs2-market-analysis

A dashboard to visualise CSFloat transactions

See [plan/cs2-market-analysis-plan.md](plan/cs2-market-analysis-plan.md) for the full design.

## Local dev setup

```bash
cp .env.example .env      # fill in CSFLOAT_API_KEY when you have one
docker compose up -d      # Postgres (port 5433) + Redpanda (Kafka-API compatible, port 9092)
uv run alembic upgrade head
uv run pytest             # unit + integration tests (needs postgres up; each test rolls back)
uv run python -m ingestion.csfloat   # polls CSFloat, publishes to raw.csfloat.listings
uv run python -m ingestion.skinport  # STUB — fake listings, for exercising arbitrage logic only
uv run python -m consolidator        # consumes raw.*.listings, writes to postgres
uv run python -m analysis            # one-shot: trend, volatility, arbitrage, underpriced_listing
uv run python -m analysis.scheduler  # runs the above on a loop (ANALYSIS_RECOMPUTE_INTERVAL_SECONDS)
uv run uvicorn api.main:app --reload # http://localhost:8000 — /skins, /listings, /analysis, /freshness
docker compose up -d dashboard       # http://localhost:3000 — Next.js dev server (Node via container, see below)
```

`DB_PORT` defaults to `5433`, not the standard `5432`, to avoid colliding with any
pre-existing local Postgres install.

### Dashboard (no local Node needed)

Node isn't required on the host — `docker-compose.yml`'s `dashboard` service runs
`next dev` inside a `node:22-alpine` container with `dashboard/` mounted in. First time only:

```bash
cp dashboard/.env.example dashboard/.env.local
```

The FastAPI server needs to be reachable from *inside* that container too, so run it bound to
all interfaces rather than just localhost: `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000`.
(`dashboard/.env.local`'s `API_BASE_URL=http://host.docker.internal:8000` is how the containerized
Next.js server reaches it; `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` is what the browser —
running on your actual machine — uses instead, since client-side code can't see `host.docker.internal`.)

To scaffold/rebuild without the compose service (e.g. `npm install` a new package):

```bash
docker run --rm -v "<repo>/dashboard:/app" -w /app node:22-alpine sh -c "npm install <package>"
```

## Layout

- `db/` — SQLAlchemy models (source of truth for the schema) + session factory, shared by everything below
- `migrations/` — Alembic migrations, generated from `db/models.py`
- `ingestion/` — per-marketplace polling plugins (`ingestion/common` holds the shared plugin interface). `ingestion/skinport` is a STUB (fake hardcoded listings, no real API) — not a real Skinport integration
- `consolidator/` — single Kafka consumer: dedups, upserts `listings`/`skin_variants`, appends `price_history`
- `analysis/` — scheduled batch modules (`trend.py`, `arbitrage.py`, `underpriced.py`) — read Postgres only, no Kafka dependency
- `api/` — FastAPI service serving `analysis_results` and listing browse/filter queries
- `dashboard/` — Next.js frontend

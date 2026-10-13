# cs2-market-analysis

A dashboard to visualise CSFloat transactions

See [plan/cs2-market-analysis-plan.md](plan/cs2-market-analysis-plan.md) for the full design.

## Local dev setup

Everything runs in Docker, so the only requirements are Docker Desktop (Compose v2.24+)
and a CSFloat API key. `uv` is only needed to run scripts or tests outside Docker.

### macOS

```bash
git clone <repo-url> && cd cs2-market-analysis
cp .env.example .env      # fill in CSFLOAT_API_KEY
docker compose up -d --build
```

### Windows

Use Docker Desktop with the WSL 2 backend, and clone the repo **inside WSL** (e.g.
`~/code` in Ubuntu), not on `C:\`. On a Windows-drive checkout, file changes often
don't reach the containers, so the dashboard won't hot-reload, and file access is much slower.

```bash
# in a WSL (Ubuntu) terminal
git clone <repo-url> && cd cs2-market-analysis
cp .env.example .env      # fill in CSFLOAT_API_KEY
docker compose up -d --build
```

From then on every command in this README works unchanged in that WSL terminal. To
edit the code, run `code .` from WSL, which opens VS Code connected to WSL.

If you do run from PowerShell on a Windows-drive checkout instead, the Docker commands
are the same; only the copy step differs: `Copy-Item .env.example .env`.

### What's running

That runs everything: Postgres (host port 5433), Redpanda (Kafka-API compatible, 9092),
migrations (one-shot), the CSFloat ingester, the consolidator, the analysis scheduler,
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
uv run python -m ingestion.skinport  # STUB — fake listings, for exercising arbitrage logic only
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
- `ingestion/` — per-marketplace polling plugins (`ingestion/common` holds the shared plugin interface). `ingestion/skinport` is a STUB (fake hardcoded listings, no real API) — not a real Skinport integration
- `consolidator/` — single Kafka consumer: dedups, upserts `listings`/`skin_variants`, appends `price_history`
- `analysis/` — scheduled batch modules (`trend.py`, `arbitrage.py`, `underpriced.py`) — read Postgres only, no Kafka dependency
- `api/` — FastAPI service serving `analysis_results` and listing browse/filter queries
- `dashboard/` — Next.js frontend

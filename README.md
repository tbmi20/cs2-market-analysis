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
uv run python -m consolidator        # consumes raw.*.listings, writes to postgres
```

`DB_PORT` defaults to `5433`, not the standard `5432`, to avoid colliding with any
pre-existing local Postgres install.

## Layout

- `db/` — SQLAlchemy models (source of truth for the schema) + session factory, shared by everything below
- `migrations/` — Alembic migrations, generated from `db/models.py`
- `ingestion/` — per-marketplace polling plugins (`ingestion/common` holds the shared plugin interface)
- `consolidator/` — single Kafka consumer: dedups, upserts `listings`/`skin_variants`, appends `price_history`
- `analysis/` — scheduled batch modules (trend, arbitrage, confidence tier) — read Postgres only, no Kafka dependency
- `api/` — FastAPI service serving `analysis_results` and listing browse/filter queries
- `dashboard/` — Next.js frontend (not yet scaffolded — needs Node installed locally)

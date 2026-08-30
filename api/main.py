"""Entrypoint: `uv run uvicorn api.main:app --reload`

Serves analysis_results and listing browse/filter queries as JSON (plan
Section 7/9 step 6). Reads Postgres only — no Kafka dependency, same as the
analysis modules.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import analysis, freshness, listings, skins

app = FastAPI(title="cs2-market-analysis API")

# The Next.js dev server runs on a different origin (localhost:3000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(skins.router)
app.include_router(listings.router)
app.include_router(analysis.router)
app.include_router(freshness.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

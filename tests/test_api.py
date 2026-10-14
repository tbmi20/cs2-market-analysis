"""API endpoint tests, isolated via the same db_session transaction/savepoint
pattern as the rest of the suite — overrides get_db so requests run inside
the test's own rolled-back transaction instead of a fresh SessionLocal().
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_db
from api.main import app
from db.models import AnalysisResult, IngestionRun, Listing, SkinVariant


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def make_variant(db_session, **overrides) -> int:
    defaults = dict(weapon="Desert Eagle", skin_name="Blaze (api-test)", wear_category="FN", float_bucket="Full FN")
    defaults.update(overrides)
    variant = SkinVariant(**defaults)
    db_session.add(variant)
    db_session.flush()
    return variant.id


def test_health(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_skins_returns_only_variants_with_active_listings(client, db_session) -> None:
    variant_id = make_variant(db_session)
    db_session.add(Listing(marketplace="csfloat", listing_id="api-1", skin_variant_id=variant_id, listing_price=100.0))
    db_session.flush()

    resp = client.get("/skins", params={"q": "Blaze (api-test)"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["weapon"] == "Desert Eagle"
    assert body[0]["active_listing_count"] == 1


def test_skins_and_listings_exclude_inactive_listings(client, db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Blaze (api-test-inactive)")
    db_session.add(Listing(marketplace="csfloat", listing_id="api-active", skin_variant_id=variant_id, listing_price=100.0))
    for status in ("sold", "delisted", "expired"):
        db_session.add(
            Listing(marketplace="csfloat", listing_id=f"api-{status}", skin_variant_id=variant_id, listing_price=90.0, status=status)
        )
    db_session.flush()

    [skin] = client.get("/skins", params={"q": "Blaze (api-test-inactive)"}).json()
    assert skin["active_listing_count"] == 1
    body = client.get("/listings", params={"weapon": "Desert Eagle", "skin_name": "Blaze (api-test-inactive)"}).json()
    assert [row["listing_id"] for row in body] == ["api-active"]


def test_list_listings_filters_by_float_range(client, db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Blaze (api-test-float)")
    db_session.add(
        Listing(marketplace="csfloat", listing_id="api-2", skin_variant_id=variant_id, float_value=0.01, listing_price=200.0)
    )
    db_session.add(
        Listing(marketplace="csfloat", listing_id="api-3", skin_variant_id=variant_id, float_value=0.5, listing_price=50.0)
    )
    db_session.flush()

    resp = client.get("/listings", params={"weapon": "Desert Eagle", "skin_name": "Blaze (api-test-float)", "float_max": 0.1})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["listing_id"] == "api-2"


def test_analysis_flags_suppressed_below_threshold(client, db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Blaze (api-test-analysis)")
    db_session.add(
        AnalysisResult(skin_variant_id=variant_id, metric_type="trend", window_days=7, value=0.1, sample_count=3, confidence_tier="low")
    )
    db_session.flush()

    resp = client.get("/analysis", params={"metric_type": "trend", "window_days": 7, "skin_variant_id": variant_id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["suppressed"] is True
    assert body[0]["sample_count"] == 3


def test_analysis_excludes_suppressed_when_asked(client, db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Blaze (api-test-exclude)")
    db_session.add(
        AnalysisResult(skin_variant_id=variant_id, metric_type="trend", window_days=7, value=0.1, sample_count=3, confidence_tier="low")
    )
    db_session.flush()

    resp = client.get(
        "/analysis",
        params={"metric_type": "trend", "window_days": 7, "skin_variant_id": variant_id, "include_suppressed": False},
    )
    assert resp.json() == []


def test_analysis_only_returns_latest_snapshot(client, db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Blaze (api-test-latest)")
    old_time = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(
        AnalysisResult(
            skin_variant_id=variant_id,
            metric_type="trend",
            window_days=7,
            value=0.05,
            sample_count=20,
            confidence_tier="high",
            computed_at=old_time,
        )
    )
    db_session.add(
        AnalysisResult(
            skin_variant_id=variant_id, metric_type="trend", window_days=7, value=0.30, sample_count=20, confidence_tier="high"
        )
    )
    db_session.flush()

    resp = client.get("/analysis", params={"metric_type": "trend", "window_days": 7, "skin_variant_id": variant_id})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["value"] == pytest.approx(0.30)


def test_analysis_handles_null_window_days_metric(client, db_session) -> None:
    variant_id = make_variant(db_session, skin_name="Blaze (api-test-arbitrage)")
    db_session.add(
        AnalysisResult(
            skin_variant_id=variant_id,
            metric_type="arbitrage",
            window_days=None,
            value=5.0,
            sample_count=1,
            confidence_tier="low",
            # Ahead of any real scheduler run, so it's the newest arbitrage run.
            computed_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            details={"cheap_marketplace": "skinport"},
        )
    )
    db_session.flush()

    resp = client.get("/analysis", params={"metric_type": "arbitrage", "skin_variant_id": variant_id})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["details"]["cheap_marketplace"] == "skinport"


def test_point_in_time_metric_drops_variants_missing_from_latest_run(client, db_session) -> None:
    # An underpriced listing flagged last run but not this one (e.g. it sold)
    # must not keep showing just because it's still its variant's newest row.
    gone_variant = make_variant(db_session, skin_name="Blaze (api-test-run-gone)")
    kept_variant = make_variant(db_session, skin_name="Blaze (api-test-run-kept)")
    previous_run = datetime.now(timezone.utc) + timedelta(minutes=1)
    latest_run = previous_run + timedelta(minutes=5)
    for variant_id, computed_at in [(gone_variant, previous_run), (kept_variant, previous_run), (kept_variant, latest_run)]:
        db_session.add(
            AnalysisResult(
                skin_variant_id=variant_id,
                metric_type="underpriced_listing",
                window_days=7,
                value=0.3,
                sample_count=20,
                confidence_tier="high",
                computed_at=computed_at,
            )
        )
    db_session.flush()

    assert client.get("/analysis", params={"metric_type": "underpriced_listing", "skin_variant_id": gone_variant}).json() == []
    [kept] = client.get("/analysis", params={"metric_type": "underpriced_listing", "skin_variant_id": kept_variant}).json()
    assert kept["skin_variant_id"] == kept_variant


def test_freshness_returns_latest_run_per_marketplace(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    db_session.add(
        IngestionRun(
            marketplace="fakemarket_freshness",
            started_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=4),
            status="success",
            records_ingested=10,
        )
    )
    db_session.add(
        IngestionRun(
            marketplace="fakemarket_freshness",
            started_at=now,
            finished_at=now,
            status="failed",
            records_ingested=0,
            error_message="boom",
        )
    )
    db_session.flush()

    resp = client.get("/freshness")
    body = [row for row in resp.json() if row["marketplace"] == "fakemarket_freshness"]
    assert len(body) == 1
    assert body[0]["last_status"] == "failed"
    assert body[0]["last_successful_poll"] is None  # latest run failed, not success

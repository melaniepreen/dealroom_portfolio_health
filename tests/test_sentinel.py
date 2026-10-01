import json
import os

import pytest
from fastapi.testclient import TestClient

from sentinel.db import connect, database_url
from sentinel.features import cadence, industry_position
from sentinel.fixture import load_fixture
from sentinel.pipeline import prepare

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_DB") == "1",
    reason="PostgreSQL is not available",
)


@pytest.fixture(scope="module")
def db():
    os.environ.setdefault("DATABASE_URL", database_url())
    try:
        with connect() as conn:
            load_fixture(conn)
            prepare(conn)
            yield conn
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


def test_model_beats_the_cadence_rule_on_a_later_month(db):
    with db.cursor() as cur:
        cur.execute("SELECT metrics FROM model_run WHERE version = 'xgboost-next-stage-v1'")
        metrics = cur.fetchone()["metrics"]
    assert metrics["device"] == "cpu"
    assert metrics["horizons"]["6"]["beats_cadence"] is True
    assert "brier" in metrics["horizons"]["6"]


def test_missing_industry_series_is_dropped(db):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM company WHERE name = 'Nila'")
        company = cur.fetchone()
    position = industry_position(db, company)
    assert "traffic_growth" in position["dropped"]
    assert position["industry"] == "Health"


def test_target_gap_only_when_a_target_exists(db):
    from sentinel.features import target_gaps

    with db.cursor() as cur:
        cur.execute("SELECT id FROM company WHERE name = 'Nila'")
        nila = cur.fetchone()["id"]
        cur.execute("SELECT id FROM company WHERE name = 'Grafit'")
        grafit = cur.fetchone()["id"]
    assert target_gaps(db, nila)["targets"]
    empty = target_gaps(db, grafit)
    assert empty["targets"] == []
    assert empty["reason"]


def test_frontier_is_compared_with_ai_not_health(db):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM company WHERE name = 'Frontier Computing'")
        company = cur.fetchone()
    position = industry_position(db, company)
    assert position["industry"] == "AI and machine learning"
    assert position["industry"] != "Health"
    assert 2026 in position["partial_years"]


def test_debt_is_excluded_from_cadence(db):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM company WHERE name = 'Bron'")
        company_id = cur.fetchone()["id"]
    clock = cadence(db, company_id)
    assert clock["last_stage"] == "Seed"
    assert clock["months_since_last_vc"] == 19


def test_stealth_miss_is_stored(db):
    with db.cursor() as cur:
        cur.execute("SELECT found_in_dealroom FROM company WHERE name = 'Stealth Climate'")
        row = cur.fetchone()
    assert row["found_in_dealroom"] is False


def test_rest_matches_mcp(db):
    from sentinel.api import app

    client = TestClient(app)
    rest = client.get("/companies/Frontier%20Computing/industry")
    mcp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_industry_position", "arguments": {"company": "Frontier Computing"}},
        },
    )
    assert rest.status_code == 200
    body = mcp.json()["result"]["content"][0]["text"]
    assert json.loads(body)["industry"] == rest.json()["industry"]


def test_alerts_cite_evidence_and_do_not_use_the_model_as_severity(db):
    from sentinel.alerts import rebuild_alerts
    from sentinel.tools import portfolio_alerts

    payload = portfolio_alerts(db)
    by_key = {(row["company"], row["type"]): row for row in payload["alerts"]}
    stealth = by_key[("Stealth Climate", "DATA_ANOMALY")]
    assert "No Dealroom" in stealth["title"]
    assert stealth["missing"] == ["dealroom_record"]
    assert stealth["next_step"]
    nila = by_key[("Nila", "TARGET_MISS")]
    assert nila["severity"] == "attention"
    assert nila["evidence"][0]["ratio"] < 1
    assert "model_score" not in nila

    with db.cursor() as cur:
        cur.execute("SELECT id FROM company WHERE name = 'Grafit'")
        grafit = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO fund_target (company_id, metric, target_value, period) VALUES (%s, 'runway', 6, 'months')",
            (grafit,),
        )
    db.commit()
    try:
        rebuild_alerts(db)
        pressure = {
            (row["company"], row["type"]): row for row in portfolio_alerts(db)["alerts"]
        }[("Grafit", "FINANCING_PRESSURE")]
        assert pressure["evidence"][0]["target"] == 6
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM fund_target WHERE company_id = %s", (grafit,))
        db.commit()
        rebuild_alerts(db)


def test_recorded_sync_keeps_debt_out_and_stores_traffic(db):
    from datetime import datetime, timezone

    from sentinel.features import venture_rounds
    from sentinel.store import apply_dealroom_record

    record = {
        "company": {
            "jobs": {"open_count": 3},
            "valuation": {"year": 2024, "month": 1},
            "locations": [{"role": "hq", "country": {"name": "United Kingdom"}}],
        },
        "rounds": [
            {"year": 2024, "month": 1, "amount": {"value": 1000000}, "standardized_round": "Seed", "is_vc_round": True},
            {"year": 2024, "month": 6, "amount": 500000, "standardized_round": "Debt", "is_vc_round": False},
        ],
        "financials": [{"year": 2025, "revenue": 250000, "employees": 9}],
        "traffic": [{"date": "2025-09-01", "value": 1400}],
        "headcount": [{"department": "engineering", "percentage": 40}],
        "team": [{"name": "Ada", "founded_companies_count": 1, "education": [{"university": "UCL"}]}],
    }
    cid = apply_dealroom_record(
        db,
        {"name": "Sample Widgets", "industry": "Health", "in_portfolio": False},
        record,
        datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    db.commit()
    try:
        rounds = venture_rounds(db, cid)
        assert [row["standardized_round"] for row in rounds] == ["Seed"]
        with db.cursor() as cur:
            cur.execute(
                "SELECT traffic FROM monthly_signal WHERE company_id = %s AND year = 2025 AND month = 9",
                (cid,),
            )
            assert cur.fetchone()["traffic"] == 1400
            cur.execute("SELECT revenue FROM filing WHERE company_id = %s AND year = 2025", (cid,))
            assert cur.fetchone()["revenue"] == 250000
            cur.execute(
                "SELECT COUNT(*) AS n FROM monthly_signal WHERE company_id = %s AND employees = 40",
                (cid,),
            )
            assert cur.fetchone()["n"] == 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM company WHERE id = %s", (cid,))
        db.commit()

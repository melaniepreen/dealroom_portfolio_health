"""Write a Dealroom company record into the internal tables."""

from __future__ import annotations

from datetime import datetime

from sentinel.normalize import (
    current_snapshot,
    employee_points_from_headcount,
    filings,
    founder_rows,
    funding_rounds,
    hq_country,
    timeseries_points,
    traffic_points,
)


def company_id(name: str) -> str:
    return name.lower().replace(" ", "-")


def apply_dealroom_record(conn, spec: dict, record: dict, fetched: datetime) -> str:
    cid = company_id(spec["name"])
    body = record.get("company") or {}
    snapshot = current_snapshot(body)
    country = hq_country(body)
    rounds = funding_rounds(record.get("rounds"))
    stage = _latest_vc_stage(rounds) or spec.get("stage_tag")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO company (
                id, name, in_portfolio, hq_country, industry_name, stage,
                jobs_open, valuation_year, valuation_month, found_in_dealroom,
                source, fetched_at, source_endpoint
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, 'dealroom', %s, '/data/companies')
            ON CONFLICT (id) DO UPDATE SET
                hq_country = EXCLUDED.hq_country,
                industry_name = EXCLUDED.industry_name,
                stage = EXCLUDED.stage,
                jobs_open = EXCLUDED.jobs_open,
                valuation_year = EXCLUDED.valuation_year,
                valuation_month = EXCLUDED.valuation_month,
                found_in_dealroom = TRUE,
                fetched_at = EXCLUDED.fetched_at,
                source_endpoint = EXCLUDED.source_endpoint
            """,
            (
                cid,
                spec["name"],
                spec.get("in_portfolio", True),
                country,
                spec["industry"],
                stage,
                snapshot["jobs_open"],
                snapshot["valuation_year"],
                snapshot["valuation_month"],
                fetched,
            ),
        )
        cur.execute("DELETE FROM funding_event WHERE company_id = %s", (cid,))
        cur.execute("DELETE FROM founder WHERE company_id = %s", (cid,))
        cur.execute("DELETE FROM filing WHERE company_id = %s", (cid,))
        cur.execute("DELETE FROM passage WHERE company_id = %s", (cid,))
        cur.execute("DELETE FROM monthly_signal WHERE company_id = %s", (cid,))
        for rnd in rounds:
            cur.execute(
                """
                INSERT INTO funding_event
                    (company_id, year, month, amount, standardized_round, is_vc_round, source, fetched_at, source_endpoint)
                VALUES (%s, %s, %s, %s, %s, %s, 'dealroom', %s, '/data/companies/{id}/funding-rounds')
                """,
                (cid, rnd["year"], rnd["month"], rnd["amount"], rnd["standardized_round"], rnd["is_vc_round"], fetched),
            )
        for person in founder_rows(record.get("team")):
            cur.execute(
                """
                INSERT INTO founder (company_id, name, prior_startup_count, university, source, fetched_at, source_endpoint)
                VALUES (%s, %s, %s, %s, 'dealroom', %s, '/data/companies/{id}/team')
                """,
                (cid, person["name"], person["prior_startup_count"], person["university"], fetched),
            )
        for filing in filings(record.get("financials")):
            cur.execute(
                """
                INSERT INTO filing (company_id, year, revenue, employees, source, fetched_at, source_endpoint)
                VALUES (%s, %s, %s, %s, 'dealroom', %s, '/data/companies/{id}/financials')
                """,
                (cid, filing["year"], filing["revenue"], filing["employees"], fetched),
            )
            if filing["employees"] is not None:
                _upsert_signal(cur, cid, filing["year"], 12, filing["employees"], None, fetched, "/data/companies/{id}/financials")
        for point in employee_points_from_headcount(record.get("headcount")):
            _upsert_signal(cur, cid, point["year"], point["month"], point["employees"], None, fetched, "/data/companies/{id}/headcount-breakdown")
        for point in traffic_points(record.get("traffic")):
            _upsert_signal(cur, cid, point["year"], point["month"], None, point["traffic"], fetched, "/data/companies/{id}/web-traffic")
        cur.execute(
            """
            INSERT INTO passage (company_id, body, source, as_of, fetched_at)
            VALUES (%s, %s, 'dealroom', CURRENT_DATE, %s)
            """,
            (cid, f"{spec['name']} synced from Dealroom in {spec['industry']}.", fetched),
        )
    return cid


def mark_not_found(conn, spec: dict, fetched: datetime) -> str:
    cid = company_id(spec["name"])
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO company (
                id, name, in_portfolio, hq_country, industry_name, stage, found_in_dealroom,
                source, fetched_at, source_endpoint
            ) VALUES (%s, %s, TRUE, 'United Kingdom', %s, %s, FALSE, 'dealroom', %s, '/data/search')
            ON CONFLICT (id) DO UPDATE SET
                found_in_dealroom = FALSE,
                fetched_at = EXCLUDED.fetched_at
            """,
            (cid, spec["name"], spec["industry"], spec.get("stage_tag"), fetched),
        )
        cur.execute("DELETE FROM passage WHERE company_id = %s", (cid,))
        cur.execute(
            """
            INSERT INTO passage (company_id, body, source, as_of, fetched_at)
            VALUES (%s, %s, 'dealroom', CURRENT_DATE, %s)
            """,
            (cid, f"No Dealroom passage for {spec['name']}.", fetched),
        )
    return cid


def apply_industry_points(conn, industry_name: str, payload, fetched: datetime, endpoint: str) -> int:
    points = timeseries_points(payload)
    with conn.cursor() as cur:
        for point in points:
            cur.execute(
                """
                INSERT INTO industry_month
                    (industry_name, year, month, vc_funding, partial, source, fetched_at, source_endpoint)
                VALUES (%s, %s, %s, %s, %s, 'dealroom', %s, %s)
                ON CONFLICT (industry_name, year, month) DO UPDATE SET
                    vc_funding = EXCLUDED.vc_funding,
                    partial = EXCLUDED.partial,
                    fetched_at = EXCLUDED.fetched_at,
                    source_endpoint = EXCLUDED.source_endpoint
                """,
                (
                    industry_name,
                    point["year"],
                    point["month"],
                    point["value"],
                    point["partial"],
                    fetched,
                    endpoint,
                ),
            )
    return len(points)


def refresh_peer_medians(conn) -> None:
    """Competitor medians from the stored panel, not from the holdings themselves."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.industry_name, m.year, m.month,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY m.employees)
                    FILTER (WHERE m.employees IS NOT NULL) AS median_employees,
                percentile_cont(0.5) WITHIN GROUP (ORDER BY m.traffic)
                    FILTER (WHERE m.traffic IS NOT NULL) AS median_traffic
            FROM monthly_signal m
            JOIN company c ON c.id = m.company_id
            WHERE NOT c.in_portfolio AND c.found_in_dealroom
            GROUP BY c.industry_name, m.year, m.month
            """
        )
        rows = list(cur.fetchall())
        for row in rows:
            cur.execute(
                """
                INSERT INTO industry_month (
                    industry_name, year, month, median_employees, median_traffic, partial,
                    source, fetched_at, source_endpoint
                ) VALUES (%s, %s, %s, %s, %s, %s, 'dealroom', NOW(), 'peer-median')
                ON CONFLICT (industry_name, year, month) DO UPDATE SET
                    median_employees = COALESCE(EXCLUDED.median_employees, industry_month.median_employees),
                    median_traffic = COALESCE(EXCLUDED.median_traffic, industry_month.median_traffic)
                """,
                (
                    row["industry_name"],
                    row["year"],
                    row["month"],
                    row["median_employees"],
                    row["median_traffic"],
                    int(row["year"]) >= 2026,
                ),
            )


def _latest_vc_stage(rounds: list[dict]) -> str | None:
    venture = [rnd for rnd in rounds if rnd["is_vc_round"] and rnd["year"] and rnd["month"]]
    if not venture:
        return None
    venture.sort(key=lambda rnd: (rnd["year"], rnd["month"]))
    return venture[-1]["standardized_round"]


def _upsert_signal(cur, cid, year, month, employees, traffic, fetched, endpoint) -> None:
    cur.execute(
        """
        INSERT INTO monthly_signal
            (company_id, year, month, employees, traffic, source, fetched_at, source_endpoint)
        VALUES (%s, %s, %s, %s, %s, 'dealroom', %s, %s)
        ON CONFLICT (company_id, year, month) DO UPDATE SET
            employees = COALESCE(EXCLUDED.employees, monthly_signal.employees),
            traffic = COALESCE(EXCLUDED.traffic, monthly_signal.traffic),
            fetched_at = EXCLUDED.fetched_at,
            source_endpoint = EXCLUDED.source_endpoint
        """,
        (cid, year, month, employees, traffic, fetched, endpoint),
    )

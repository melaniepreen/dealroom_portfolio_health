"""Recorded company database used by tests and by the local page before a live sync.

Numbers are an illustration of a Dealroom pull, tagged source=dealroom, so the
tools can run without a key. A live sync replaces public companies.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sentinel.portfolio import PORTFOLIO

FETCHED = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _months(start_year: int, start_month: int, count: int, start_value: float, step: float):
    points = []
    year, month = start_year, start_month
    value = start_value
    for _ in range(count):
        points.append((year, month, value))
        value += step
        month += 1
        if month == 13:
            month = 1
            year += 1
    return points


def load_fixture(conn) -> None:
    from sentinel.db import reset_schema

    reset_schema(conn)
    with conn.cursor() as cur:
        for company in PORTFOLIO:
            found = company["public"]
            cur.execute(
                """
                INSERT INTO company (id, name, in_portfolio, hq_country, industry_name, stage,
                    found_in_dealroom, source, fetched_at, source_endpoint)
                VALUES (%s, %s, TRUE, 'United Kingdom', %s, %s, %s, 'dealroom', %s, '/data/search')
                """,
                (
                    company["name"].lower().replace(" ", "-"),
                    company["name"],
                    company["industry"],
                    company["stage_tag"] if found else None,
                    found,
                    FETCHED,
                ),
            )
            if not found:
                cur.execute(
                    """
                    INSERT INTO passage (company_id, body, source, as_of, fetched_at)
                    VALUES (%s, %s, 'dealroom', DATE '2026-10-01', %s)
                    """,
                    (
                        company["name"].lower().replace(" ", "-"),
                        f"No Dealroom passage for {company['name']}.",
                        FETCHED,
                    ),
                )
                continue
            _load_public(cur, company)
        _load_training_panel(cur)
        _load_industry_series(cur)
    conn.commit()


def _cid(name: str) -> str:
    return name.lower().replace(" ", "-")


def _load_public(cur, company: dict) -> None:
    cid = _cid(company["name"])
    rounds = _rounds_for(company["name"])
    for year, month, amount, stage, is_vc in rounds:
        cur.execute(
            """
            INSERT INTO funding_event
                (company_id, year, month, amount, standardized_round, is_vc_round, source, fetched_at, source_endpoint)
            VALUES (%s, %s, %s, %s, %s, %s, 'dealroom', %s, '/data/companies/{id}/funding-rounds')
            """,
            (cid, year, month, amount, stage, is_vc, FETCHED),
        )
    employees = _months(2024, 11, 12, 8 if company["name"] != "Nila" else 4, 0.4)
    traffic_step = 0 if company["name"] == "Nila" else 1000
    traffic_base = None if company["name"] == "Nila" else 5000
    for year, month, employees_value in employees:
        traffic = None if traffic_base is None else traffic_base + traffic_step * ((year - 2024) * 12 + month)
        cur.execute(
            """
            INSERT INTO monthly_signal
                (company_id, year, month, employees, traffic, source, fetched_at, source_endpoint)
            VALUES (%s, %s, %s, %s, %s, 'dealroom', %s, '/data/companies/{id}/financials')
            """,
            (cid, year, month, employees_value, traffic, FETCHED),
        )
    cur.execute(
        """
        INSERT INTO filing (company_id, year, revenue, employees, source, fetched_at, source_endpoint)
        VALUES (%s, 2025, %s, %s, 'dealroom', %s, '/data/companies/{id}/financials')
        """,
        (cid, 500000 if company["name"] != "Nila" else None, employees[-1][2], FETCHED),
    )
    prior = 1 if company["name"] in {"Bron", "Dexory"} else 0
    university = "Imperial College London" if company["name"] == "Dexory" else None
    cur.execute(
        """
        INSERT INTO founder (company_id, name, prior_startup_count, university, source, fetched_at, source_endpoint)
        VALUES (%s, %s, %s, %s, 'dealroom', %s, '/data/companies/{id}/team')
        """,
        (cid, f"{company['name']} founder", prior, university, FETCHED),
    )
    if company["name"] == "Nila":
        cur.execute(
            """
            INSERT INTO fund_target (company_id, metric, target_value, period)
            VALUES (%s, 'employees', 12, '2026')
            """,
            (cid,),
        )
    cur.execute(
        """
        INSERT INTO passage (company_id, body, source, as_of, fetched_at)
        VALUES (%s, %s, 'dealroom', DATE '2026-10-01', %s)
        """,
        (
            cid,
            f"{company['name']} is stored from Dealroom in {company['industry']}, stage {company['stage_tag']}.",
            FETCHED,
        ),
    )


def _rounds_for(name: str) -> list[tuple]:
    if name == "Bron":
        return [
            (2023, 1, 400000, "Pre-Seed", True),
            (2025, 3, 2500000, "Seed", True),
            (2025, 11, 500000, "Debt", False),
        ]
    if name == "Nila":
        return [(2025, 6, 600000, "Pre-Seed", True)]
    if name == "Frontier Computing":
        return [(2026, 2, 800000, "Pre-Seed", True)]
    if name == "Grafit":
        return [(2025, 8, 3000000, "Seed", True)]
    if name == "Catalog":
        return [
            (2022, 4, 1500000, "Seed", True),
            (2024, 6, 12000000, "Series A", True),
        ]
    if name == "Dexory":
        return [
            (2021, 5, 2000000, "Seed", True),
            (2024, 3, 15000000, "Series A", True),
        ]
    return []


def _load_industry_series(cur) -> None:
    industries = {company["industry"] for company in PORTFOLIO if company["public"]}
    for industry in industries:
        base = 20 if industry != "Health" else 15
        traffic = 8000 if industry != "Health" else 4000
        for year, month, value in _months(2024, 1, 34, base, 0.2):
            cur.execute(
                """
                INSERT INTO industry_month (
                    industry_name, year, month, vc_funding, median_employees, median_traffic,
                    partial, source, fetched_at, source_endpoint
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'dealroom', %s, '/analytics/timeseries?metric=vc_funding')
                """,
                (
                    industry,
                    year,
                    month,
                    1_000_000 + value * 1000,
                    value,
                    traffic,
                    year >= 2026,
                    FETCHED,
                ),
            )


def _load_training_panel(cur) -> None:
    """Extra UK companies so XGBoost is not fit on the six holdings alone."""
    for index in range(24):
        cid = f"panel-{index}"
        stage = "Seed" if index % 2 == 0 else "Pre-Seed"
        industry = "Health" if index % 3 == 0 else "AI and machine learning"
        raised_next = index % 4 == 0
        cur.execute(
            """
            INSERT INTO company (id, name, in_portfolio, hq_country, industry_name, stage,
                found_in_dealroom, source, fetched_at, source_endpoint)
            VALUES (%s, %s, FALSE, 'United Kingdom', %s, %s, TRUE, 'dealroom', %s, '/data/companies')
            """,
            (cid, f"Panel {index}", industry, stage, FETCHED),
        )
        cur.execute(
            """
            INSERT INTO funding_event
                (company_id, year, month, amount, standardized_round, is_vc_round, source, fetched_at, source_endpoint)
            VALUES (%s, 2024, 1, 1000000, %s, TRUE, 'dealroom', %s, '/data/companies/{id}/funding-rounds')
            """,
            (cid, stage, FETCHED),
        )
        if raised_next:
            nxt = "Series A" if stage == "Seed" else "Seed"
            cur.execute(
                """
                INSERT INTO funding_event
                    (company_id, year, month, amount, standardized_round, is_vc_round, source, fetched_at, source_endpoint)
                VALUES (%s, 2024, 6, 4000000, %s, TRUE, 'dealroom', %s, '/data/companies/{id}/funding-rounds')
                """,
                (cid, nxt, FETCHED),
            )
        cur.execute(
            """
            INSERT INTO founder (company_id, name, prior_startup_count, university, source, fetched_at, source_endpoint)
            VALUES (%s, %s, %s, %s, 'dealroom', %s, '/data/companies/{id}/team')
            """,
            (cid, f"Founder {index}", 1 if raised_next else 0, "University of Cambridge" if raised_next else None, FETCHED),
        )
        for year, month, employees in _months(2024, 1, 8, 6 + index % 3, 0.3):
            cur.execute(
                """
                INSERT INTO monthly_signal
                    (company_id, year, month, employees, traffic, source, fetched_at, source_endpoint)
                VALUES (%s, %s, %s, %s, %s, 'dealroom', %s, '/data/companies/{id}/web-traffic')
                """,
                (cid, year, month, employees, 2000 + index * 10, FETCHED),
            )

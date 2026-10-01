"""Feature panel read from the company database."""

from __future__ import annotations

import math
from statistics import median

from sentinel.portfolio import AS_OF, next_stage

AS_OF_YEAR, AS_OF_MONTH = AS_OF


def months_between(year_a: int, month_a: int, year_b: int, month_b: int) -> int:
    return (year_b - year_a) * 12 + (month_b - month_a)


def venture_rounds(conn, company_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, amount, standardized_round
            FROM funding_event
            WHERE company_id = %s AND is_vc_round AND year IS NOT NULL AND month BETWEEN 1 AND 12
            ORDER BY year, month
            """,
            (company_id,),
        )
        return list(cur.fetchall())


def cadence(conn, company_id: str) -> dict:
    rounds = venture_rounds(conn, company_id)
    if not rounds:
        return {
            "months_since_last_vc": None,
            "own_spacing": None,
            "last_stage": None,
            "last_amount": None,
            "reason": "No venture round is stored. Debt and grants do not start the clock.",
        }
    last = rounds[-1]
    gaps = [
        months_between(rounds[i]["year"], rounds[i]["month"], rounds[i + 1]["year"], rounds[i + 1]["month"])
        for i in range(len(rounds) - 1)
    ]
    return {
        "months_since_last_vc": months_between(last["year"], last["month"], AS_OF_YEAR, AS_OF_MONTH),
        "own_spacing": float(median(gaps)) if gaps else None,
        "last_stage": last["standardized_round"],
        "last_amount": last["amount"],
        "reason": None,
    }


def latest_signal(conn, company_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, employees, traffic
            FROM monthly_signal
            WHERE company_id = %s
            ORDER BY year DESC, month DESC
            LIMIT 1
            """,
            (company_id,),
        )
        return cur.fetchone()


def industry_position(conn, company: dict) -> dict:
    signal = latest_signal(conn, company["id"])
    industry = company["industry_name"]
    ratios = {}
    dropped = []
    if signal is None or signal["employees"] is None:
        dropped.append("employee_growth")
    else:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT median_employees FROM industry_month
                WHERE industry_name = %s AND year = %s AND month = %s
                """,
                (industry, signal["year"], signal["month"]),
            )
            row = cur.fetchone()
        if row is None or not row["median_employees"]:
            dropped.append("employee_growth")
        else:
            ratios["employee_growth"] = signal["employees"] / row["median_employees"]
    if signal is None or signal["traffic"] is None:
        dropped.append("traffic_growth")
    else:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT median_traffic FROM industry_month
                WHERE industry_name = %s AND year = %s AND month = %s
                """,
                (industry, signal["year"], signal["month"]),
            )
            row = cur.fetchone()
        if row is None or not row["median_traffic"]:
            dropped.append("traffic_growth")
        else:
            ratios["traffic_growth"] = signal["traffic"] / row["median_traffic"]
    position = None
    if ratios:
        logs = [math.log(value) for value in ratios.values() if value and value > 0]
        if logs:
            position = math.exp(sum(logs) / len(logs))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT year FROM industry_month
            WHERE industry_name = %s AND partial
            ORDER BY year
            """,
            (industry,),
        )
        partial_years = [row["year"] for row in cur.fetchall()]
    return {
        "industry": industry,
        "ratios": ratios,
        "industry_position": position,
        "dropped": dropped,
        "partial_years": partial_years,
    }


def target_gaps(conn, company_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT metric, target_value, period FROM fund_target WHERE company_id = %s",
            (company_id,),
        )
        targets = list(cur.fetchall())
    if not targets:
        return {"targets": [], "reason": "No fund target has been entered for this company."}
    signal = latest_signal(conn, company_id)
    rows = []
    for target in targets:
        actual = None
        if target["metric"] == "employees" and signal is not None:
            actual = signal["employees"]
        ratio = None if actual is None or not target["target_value"] else actual / target["target_value"]
        rows.append(
            {
                "metric": target["metric"],
                "target": target["target_value"],
                "period": target["period"],
                "actual": actual,
                "ratio": ratio,
            }
        )
    return {"targets": rows, "reason": None}


def founder_features(conn, company_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT prior_startup_count, university FROM founder WHERE company_id = %s
            """,
            (company_id,),
        )
        rows = list(cur.fetchall())
    if not rows:
        return {"prior_startup_count": None, "university": None, "missing": ["prior_startup", "university"]}
    known_counts = [row["prior_startup_count"] for row in rows if row["prior_startup_count"] is not None]
    count = max(known_counts) if known_counts else None
    universities = [row["university"] for row in rows if row["university"]]
    missing = [] if count is not None else ["prior_startup"]
    if not universities:
        missing.append("university")
    return {
        "prior_startup_count": count,
        "university": universities[0] if universities else None,
        "missing": missing,
    }


def signal_as_of(conn, company_id: str, year: int, month: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, employees, traffic
            FROM monthly_signal
            WHERE company_id = %s
              AND (year < %s OR (year = %s AND month <= %s))
            ORDER BY year DESC, month DESC
            LIMIT 1
            """,
            (company_id, year, year, month),
        )
        return cur.fetchone()


def industry_as_of(conn, industry_name: str, year: int, month: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vc_funding, median_employees, median_traffic, partial
            FROM industry_month
            WHERE industry_name = %s AND year = %s AND month = %s
            """,
            (industry_name, year, month),
        )
        return cur.fetchone()


def company_by_name(conn, name: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM company WHERE lower(name) = lower(%s)", (name,))
        return cur.fetchone()


def feature_row(conn, company: dict) -> dict:
    clock = cadence(conn, company["id"])
    position = industry_position(conn, company)
    founders = founder_features(conn, company["id"])
    signal = latest_signal(conn, company["id"])
    missing = list(position["dropped"]) + list(founders["missing"])
    if clock["months_since_last_vc"] is None:
        missing.append("months_since_last_vc")
    stage = clock["last_stage"] or company["stage"]
    return {
        "stage": stage,
        "next_stage": next_stage(stage),
        "last_amount": clock["last_amount"],
        "months_since_last_vc": clock["months_since_last_vc"],
        "own_spacing": clock["own_spacing"],
        "employees": None if signal is None else signal["employees"],
        "traffic": None if signal is None else signal["traffic"],
        "industry": position["industry"],
        "industry_position": position["industry_position"],
        "prior_startup_count": founders["prior_startup_count"],
        "university": founders["university"],
        "missing": missing,
        "cadence_reason": clock["reason"],
    }

"""Shared answers for the local page, REST, and MCP."""

from __future__ import annotations

import json

from sentinel.features import company_by_name, feature_row, industry_position, target_gaps
from sentinel.model import VERSION


def portfolio_alerts(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.*, c.name AS company
            FROM alert a JOIN company c ON c.id = a.company_id
            WHERE c.in_portfolio
            ORDER BY c.name, a.type
            """
        )
        rows = [_alert_row(row) for row in cur.fetchall()]
    return {"alerts": rows}


def company_changes(conn, name: str, lookback: int = 6) -> dict:
    company = _require(conn, name)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, employees, traffic FROM monthly_signal
            WHERE company_id = %s ORDER BY year, month
            """,
            (company["id"],),
        )
        points = list(cur.fetchall())
    window = points[-lookback:] if points else []
    features = []
    if window:
        features.append(_change("employees", window))
        features.append(_change("traffic", window))
    return {"company": company["name"], "lookback_months": lookback, "features": features, "found": company["found_in_dealroom"]}


def company_prediction(conn, name: str) -> dict:
    company = _require(conn, name)
    if not company["found_in_dealroom"]:
        return {
            "company": company["name"],
            "found": False,
            "note": "No Dealroom passage for this company. Neither score means the company is fundraising.",
        }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM prediction WHERE company_id = %s ORDER BY horizon_months",
            (company["id"],),
        )
        rows = list(cur.fetchall())
    horizons = []
    for row in rows:
        horizons.append(
            {
                "months": row["horizon_months"],
                "next_stage": row["next_stage"],
                "cadence_score": row["cadence_score"],
                "model_score": row["model_score"],
                "model_version": row["model_version"] or VERSION,
                "feature_gains": row["feature_gains"],
                "missing_features": row["missing_features"],
                "months_since_last_vc": row["months_since_last_vc"],
                "own_spacing": row["own_spacing"],
            }
        )
    return {
        "company": company["name"],
        "found": True,
        "horizons": horizons,
        "note": "Neither the cadence rule nor the model score means the company is fundraising.",
    }


def industry_view(conn, name: str) -> dict:
    company = _require(conn, name)
    if not company["found_in_dealroom"]:
        return {"company": company["name"], "industry": company["industry_name"], "ratios": {}, "dropped": ["dealroom_record"], "industry_position": None}
    position = industry_position(conn, company)
    return {"company": company["name"], **position}


def company_targets(conn, name: str) -> dict:
    company = _require(conn, name)
    payload = target_gaps(conn, company["id"])
    return {"company": company["name"], **payload}


def retrieve_context(conn, query: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.name, p.body, p.source, p.as_of, p.fetched_at
            FROM passage p JOIN company c ON c.id = p.company_id
            WHERE p.body ILIKE %s OR c.name ILIKE %s
            ORDER BY c.name
            """,
            (f"%{query}%", f"%{query}%"),
        )
        rows = list(cur.fetchall())
    if not rows:
        return {"passages": [], "reason": "No stored passage matches this question."}
    return {
        "passages": [
            {
                "company": row["name"],
                "body": row["body"],
                "source": row["source"],
                "as_of": str(row["as_of"]) if row["as_of"] else None,
                "fetched_at": row["fetched_at"].isoformat() if row["fetched_at"] else None,
            }
            for row in rows
        ]
    }


def company_brief(conn, name: str) -> dict:
    company = _require(conn, name)
    prediction = company_prediction(conn, name)
    position = industry_view(conn, name)
    targets = company_targets(conn, name)
    changes = company_changes(conn, name)
    row = feature_row(conn, company) if company["found_in_dealroom"] else {}
    six = next((item for item in prediction.get("horizons", []) if item["months"] == 6), None)
    ready = None if six is None or six["model_score"] is None else six["model_score"] >= 0.5
    return {
        "company": company["name"],
        "question": f"Should I preempt a {row.get('next_stage') or 'raise'} for {company['name']}?",
        "readiness": {
            "next_stage": row.get("next_stage"),
            "signal": ready,
            "model_score_6m": None if six is None else six["model_score"],
            "cadence_score_6m": None if six is None else six["cadence_score"],
            "note": "This signal is not a decision to lead the round.",
        },
        "graph_svg": competitor_svg(conn, company),
        "founder": {
            "prior_startup_count": row.get("prior_startup_count"),
            "university": row.get("university"),
            "feature_gains": None if six is None else six.get("feature_gains"),
            "gain_note": "Founder and university weights are the gain learned from training history. A missing gain means the field was absent or was not among the top splits. Schools are not given a manual boost.",
        },
        "industry": position,
        "targets": targets,
        "changes": changes,
        "missing": row.get("missing", ["dealroom_record"] if not company["found_in_dealroom"] else []),
        "next_step": _next_step(ready, company["found_in_dealroom"]),
        "prediction": prediction,
    }


def competitor_svg(conn, company: dict) -> str:
    if not company["found_in_dealroom"]:
        return ""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, employees FROM monthly_signal
            WHERE company_id = %s AND employees IS NOT NULL
            ORDER BY year, month
            """,
            (company["id"],),
        )
        company_points = list(cur.fetchall())
        cur.execute(
            """
            SELECT year, month, median_employees FROM industry_month
            WHERE industry_name = %s AND median_employees IS NOT NULL
            ORDER BY year, month
            """,
            (company["industry_name"],),
        )
        industry_points = {(row["year"], row["month"]): row["median_employees"] for row in cur.fetchall()}
    if not company_points:
        return ""
    series = []
    competitor = []
    for row in company_points:
        series.append(row["employees"])
        competitor.append(industry_points.get((row["year"], row["month"]), row["employees"]))
    return _svg(series, competitor)


def _svg(company_values: list[float], competitor_values: list[float]) -> str:
    width, height, pad = 420, 160, 24
    values = company_values + competitor_values
    low, high = min(values), max(values)
    span = high - low or 1

    def xy(index: int, value: float, count: int) -> tuple[float, float]:
        x = pad + (width - 2 * pad) * (index / max(count - 1, 1))
        y = height - pad - (height - 2 * pad) * ((value - low) / span)
        return x, y

    def polyline(values: list[float]) -> str:
        return " ".join(f"{xy(i, value, len(values))[0]:.1f},{xy(i, value, len(values))[1]:.1f}" for i, value in enumerate(values))

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img">'
        f'<text x="{pad}" y="16" font-size="12">Employees vs competitor median</text>'
        f'<polyline fill="none" stroke="currentColor" stroke-width="2" points="{polyline(company_values)}"/>'
        f'<polyline fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="4 3" points="{polyline(competitor_values)}"/>'
        f"</svg>"
    )


def _change(field: str, window: list[dict]) -> dict:
    start = window[0][field]
    end = window[-1][field]
    direction = "flat"
    if start is not None and end is not None:
        if end > start:
            direction = "up"
        elif end < start:
            direction = "down"
    return {
        "feature": field,
        "start": start,
        "latest": end,
        "direction": direction,
        "points": [{"year": row["year"], "month": row["month"], "value": row[field]} for row in window],
    }


def _next_step(ready: bool | None, found: bool) -> str:
    if not found:
        return "Wait. There is no Dealroom record to compare with competitors."
    if ready:
        return "Discuss financing timing, or help the founder find a lead. Do not treat the score as a decision to lead."
    return "Wait until the company is closer to competitor pace or a fund target."


def _require(conn, name: str) -> dict:
    company = company_by_name(conn, name)
    if company is None:
        raise KeyError(name)
    return company


def _alert_row(row: dict) -> dict:
    return {
        "company": row["company"],
        "type": row["type"],
        "severity": row["severity"],
        "title": row["title"],
        "summary": row["summary"],
        "evidence": row["evidence"],
        "missing": row["missing"],
        "next_step": row["next_step"],
    }


def dispatch(conn, name: str, arguments: dict):
    if name == "get_portfolio_alerts":
        return portfolio_alerts(conn)
    if name == "get_company_changes":
        return company_changes(conn, arguments["company"], int(arguments.get("lookback", 6)))
    if name == "get_company_prediction":
        return company_prediction(conn, arguments["company"])
    if name == "get_industry_position":
        return industry_view(conn, arguments["company"])
    if name == "get_company_targets":
        return company_targets(conn, arguments["company"])
    if name == "generate_company_brief":
        return company_brief(conn, arguments["company"])
    if name == "retrieve_context":
        return retrieve_context(conn, arguments.get("query", ""))
    raise KeyError(name)


TOOL_NAMES = [
    "retrieve_context",
    "get_portfolio_alerts",
    "get_company_changes",
    "get_company_prediction",
    "get_industry_position",
    "get_company_targets",
    "generate_company_brief",
]


def dumps(payload) -> str:
    return json.dumps(payload, default=str)

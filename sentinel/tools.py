"""Shared answers for the local page, REST, and MCP."""

from __future__ import annotations

import json

from xml.sax.saxutils import escape as xml_escape

from sentinel.features import company_by_name, feature_row, industry_as_of, industry_position, target_gaps
from sentinel.model import FEATURE_NAMES, VERSION


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


FEATURE_DETAILS = {
    "stage": "Last venture round’s standardised stage, numbered from Pre-Seed.",
    "last_amount": "Amount of that last venture round.",
    "months_since_last_vc": "Months since that round. Debt does not reset the clock.",
    "own_spacing": "This company’s own typical gap between venture rounds, in months.",
    "employees": "Headcount in the latest stored month.",
    "traffic": "Web visits in the latest stored month.",
    "industry_vc_funding": "UK venture funding that month in this company’s industry.",
    "industry_position": "Geometric mean of the company-versus-industry ratios that exist.",
    "prior_startup": "Most companies already founded by anyone on the team.",
    "university": "First listed school. A missing school stays missing. No school is boosted by hand.",
}

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def month_label(year: int, month: int) -> str:
    return f"{_MONTHS[month - 1]} {year}"


def book_summaries(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.name, c.industry_name,
                (
                    SELECT standardized_round FROM funding_event
                    WHERE company_id = c.id AND is_vc_round
                    ORDER BY year DESC, month DESC LIMIT 1
                ) AS series,
                (
                    SELECT year FROM funding_event
                    WHERE company_id = c.id AND is_vc_round
                    ORDER BY year DESC, month DESC LIMIT 1
                ) AS year,
                (
                    SELECT month FROM funding_event
                    WHERE company_id = c.id AND is_vc_round
                    ORDER BY year DESC, month DESC LIMIT 1
                ) AS month
            FROM company c
            WHERE c.in_portfolio
            ORDER BY c.name
            """
        )
        rows = list(cur.fetchall())
    cards = []
    for row in rows:
        when = month_label(row["year"], row["month"]) if row["year"] and row["month"] else None
        cards.append(
            {
                "name": row["name"],
                "industry": row["industry_name"],
                "series": row["series"],
                "last_venture_round": when,
            }
        )
    return cards


def _rounds(conn, company_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, amount, standardized_round, is_vc_round
            FROM funding_event
            WHERE company_id = %s
            ORDER BY year, month
            """,
            (company_id,),
        )
        rows = list(cur.fetchall())
    return [
        {
            "year": row["year"],
            "month": row["month"],
            "label": month_label(row["year"], row["month"]) if row["year"] and row["month"] else None,
            "amount": row["amount"],
            "stage": row["standardized_round"],
            "is_vc_round": row["is_vc_round"],
        }
        for row in rows
    ]


def _history(conn, company: dict) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, employees, traffic FROM monthly_signal
            WHERE company_id = %s ORDER BY year, month
            """,
            (company["id"],),
        )
        points = list(cur.fetchall())
        cur.execute(
            """
            SELECT year, month, median_employees, median_traffic
            FROM industry_month WHERE industry_name = %s
            """,
            (company["industry_name"],),
        )
        peers = {(row["year"], row["month"]): row for row in cur.fetchall()}
    employees = []
    traffic = []
    for point in points:
        peer = peers.get((point["year"], point["month"]))
        label = month_label(point["year"], point["month"])
        employees.append(
            {
                "label": label,
                "company": point["employees"],
                "competitor_median": None if peer is None else peer["median_employees"],
            }
        )
        traffic.append(
            {
                "label": label,
                "company": point["traffic"],
                "competitor_median": None if peer is None else peer["median_traffic"],
            }
        )
    return {"employees": employees, "traffic": traffic}


def _model_features(conn, company: dict, row: dict, gains: dict | None) -> list[dict]:
    year_month = None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month FROM monthly_signal
            WHERE company_id = %s ORDER BY year DESC, month DESC LIMIT 1
            """,
            (company["id"],),
        )
        year_month = cur.fetchone()
    funding = None
    if year_month:
        industry = industry_as_of(conn, company["industry_name"], year_month["year"], year_month["month"])
        funding = None if industry is None else industry["vc_funding"]
    values = {
        "stage": row.get("stage"),
        "last_amount": row.get("last_amount"),
        "months_since_last_vc": row.get("months_since_last_vc"),
        "own_spacing": row.get("own_spacing"),
        "employees": row.get("employees"),
        "traffic": row.get("traffic"),
        "industry_vc_funding": funding,
        "industry_position": row.get("industry_position"),
        "prior_startup": row.get("prior_startup_count"),
        "university": row.get("university"),
    }
    recorded = gains or {}
    features = []
    for name in FEATURE_NAMES:
        value = values.get(name)
        features.append(
            {
                "name": name,
                "description": FEATURE_DETAILS[name],
                "value": value,
                "missing": value is None,
                "gain": recorded.get(name),
            }
        )
    return features


def company_brief(conn, name: str) -> dict:
    company = _require(conn, name)
    prediction = company_prediction(conn, name)
    position = industry_view(conn, name)
    targets = company_targets(conn, name)
    changes = company_changes(conn, name)
    row = feature_row(conn, company) if company["found_in_dealroom"] else {}
    six = next((item for item in prediction.get("horizons", []) if item["months"] == 6), None)
    ready = None if six is None or six["model_score"] is None else six["model_score"] >= 0.7
    gains = None if six is None else six.get("feature_gains")
    rounds = _rounds(conn, company["id"]) if company["found_in_dealroom"] else []
    history = _history(conn, company) if company["found_in_dealroom"] else {"employees": [], "traffic": []}
    features = _model_features(conn, company, row, gains) if company["found_in_dealroom"] else []
    if six and six.get("model_version", "").startswith("xgboost-dealroom-live"):
        import math
        from sentinel.real_model import FEATURES, DESCRIPTIONS, snapshot, month_id
        from sentinel.features import venture_rounds
        from sentinel.portfolio import AS_OF
        vector = snapshot(venture_rounds(conn, company["id"]), month_id(*AS_OF))
        features = [{"name": name, "description": description,
                     "value": None if vector is None or math.isnan(vector[i]) else vector[i],
                     "missing": vector is None or math.isnan(vector[i]),
                     "gain": (gains or {}).get(name)}
                    for i, (name, description) in enumerate(zip(FEATURES, DESCRIPTIONS))]
    last_venture = next((item for item in reversed(rounds) if item["is_vc_round"]), None)
    employees_svg = dated_line_svg("Employees", "Headcount", history["employees"])
    traffic_svg = dated_line_svg("Web traffic", "Visits", history["traffic"])
    return {
        "company": company["name"],
        "question": f"Should I preempt a {row.get('next_stage') or 'raise'} for {company['name']}?",
        "book": book_summaries(conn),
        "summary": {
            "series": row.get("stage"),
            "next_stage": row.get("next_stage"),
            "industry": company["industry_name"],
            "hq_country": company["hq_country"],
            "last_venture_round": last_venture,
            "months_since_last_vc": row.get("months_since_last_vc"),
            "own_spacing": row.get("own_spacing"),
            "rounds": rounds,
            "prior_startup_count": row.get("prior_startup_count"),
            "university": row.get("university"),
        },
        "history": history,
        "model_features": features,
        "readiness": {
            "next_stage": row.get("next_stage"),
            "signal": ready,
            "model_score_6m": None if six is None else six["model_score"],
            "cadence_score_6m": None if six is None else six["cadence_score"],
            "note": "This signal is not a decision to lead the round.",
        },
        "graph_svg": employees_svg,
        "traffic_svg": traffic_svg,
        "round_svg": round_timeline_svg(rounds),
        "gain_svg": gain_svg(features),
        "horizon_svg": horizon_svg(prediction.get("horizons") or []),
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


def _tick_label(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value - round(value)) < 0.05:
        return f"{value:.0f}"
    return f"{value:.1f}"


def _axis_ticks(low: float, high: float, count: int = 5) -> list[float]:
    import math

    if high <= low:
        high = low + 1
    raw = (high - low) / max(count - 1, 1)
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = magnitude
    for multiplier in (1, 2, 2.5, 5, 10):
        if multiplier * magnitude >= raw * 0.85:
            step = multiplier * magnitude
            break
    start = math.floor(low / step) * step
    ticks = []
    value = start
    while value <= high + step * 0.5:
        ticks.append(round(value, 6))
        value += step
        if len(ticks) > 8:
            break
    return ticks


def dated_line_svg(title: str, unit: str, points: list[dict]) -> str:
    usable = [point for point in points if point["company"] is not None]
    if len(usable) < 2:
        return ""
    width, height = 680, 280
    left, right, top, bottom = 78, 16, 36, 40
    values = [point["company"] for point in usable]
    values += [point["competitor_median"] for point in usable if point["competitor_median"] is not None]
    ticks = _axis_ticks(min(values), max(values))
    low, high = ticks[0], ticks[-1]
    span = high - low or 1
    count = len(usable)
    plot_bottom = height - bottom
    plot_height = plot_bottom - top

    def x_at(index: int) -> float:
        return left + (width - left - right) * (index / max(count - 1, 1))

    def y_at(value: float) -> float:
        return plot_bottom - plot_height * ((value - low) / span)

    def polyline(key: str) -> str:
        coords = []
        for index, point in enumerate(usable):
            if point[key] is None:
                continue
            coords.append(f"{x_at(index):.1f},{y_at(point[key]):.1f}")
        return " ".join(coords)

    grid = []
    for tick in ticks:
        y = y_at(tick)
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e2e2e2"/>'
            f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end">{_tick_label(tick)}</text>'
        )
    for index in range(count):
        x = x_at(index)
        grid.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{plot_bottom}" stroke="#f0f0f0"/>')
    labels = []
    for index in sorted({0, count // 2, count - 1}):
        anchor = "start" if index == 0 else "end" if index == count - 1 else "middle"
        labels.append(
            f'<text x="{x_at(index):.1f}" y="{height - 14}" font-size="11" text-anchor="{anchor}">{xml_escape(usable[index]["label"])}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{xml_escape(title)}">'
        f'<text x="{left}" y="16" font-size="13">{xml_escape(title)} ({xml_escape(unit)})</text>'
        f'<text x="{width - right}" y="16" font-size="11" text-anchor="end" fill="#1d4e89">Company</text>'
        f'<text x="{width - right - 78}" y="16" font-size="11" text-anchor="end" fill="#c47b2b">Competitor median</text>'
        f'{"".join(grid)}'
        f'<polyline fill="none" stroke="#1d4e89" stroke-width="2.5" points="{polyline("company")}"/>'
        f'<polyline fill="none" stroke="#c47b2b" stroke-width="2.5" stroke-dasharray="5 3" points="{polyline("competitor_median")}"/>'
        f'{"".join(labels)}'
        f"</svg>"
    )


def round_timeline_svg(rounds: list[dict]) -> str:
    dated = [row for row in rounds if row["year"] and row["month"]]
    if not dated:
        return ""
    width, height = 680, 120
    left, right = 72, 72
    start = dated[0]["year"] * 12 + dated[0]["month"]
    end = max(dated[-1]["year"] * 12 + dated[-1]["month"], 2026 * 12 + 10)
    span = max(end - start, 1)

    def x_for(year: int, month: int) -> float:
        return left + (width - left - right) * ((year * 12 + month - start) / span)

    marks = []
    for row in dated:
        x = x_for(row["year"], row["month"])
        kind = "Venture" if row["is_vc_round"] else "Not venture"
        fill = "#1d4e89" if row["is_vc_round"] else "#ffffff"
        stage = row["stage"] or kind
        anchor = "start" if x < 140 else "end" if x > width - 140 else "middle"
        marks.append(
            f'<line x1="{x:.1f}" y1="36" x2="{x:.1f}" y2="62" stroke="#1d4e89"/>'
            f'<circle cx="{x:.1f}" cy="62" r="5" fill="{fill}" stroke="#1d4e89"/>'
            f'<text x="{x:.1f}" y="28" font-size="11" text-anchor="{anchor}">{xml_escape(str(stage))}</text>'
            f'<text x="{x:.1f}" y="84" font-size="11" text-anchor="{anchor}">{xml_escape(row["label"] or "")}</text>'
            f'<text x="{x:.1f}" y="98" font-size="10" text-anchor="{anchor}" fill="#555">{kind}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Funding dates">'
        f'<line x1="{left}" y1="62" x2="{width - right}" y2="62" stroke="#bbb"/>'
        f'{"".join(marks)}'
        f"</svg>"
    )


def gain_svg(features: list[dict]) -> str:
    ranked = sorted(features, key=lambda item: item["gain"] or 0, reverse=True)
    if not any(item["gain"] for item in ranked):
        return ""
    width, row_h = 680, 22
    left, bar_left = 150, 210
    height = 28 + row_h * len(ranked)
    peak = max(item["gain"] or 0 for item in ranked) or 1
    bars = []
    for index, item in enumerate(ranked):
        y = 24 + index * row_h
        gain = item["gain"] or 0
        length = (width - bar_left - 70) * (gain / peak)
        label = "no split" if item["gain"] is None else f"{gain:.1f}"
        bars.append(
            f'<text x="{left}" y="{y + 12}" font-size="12" text-anchor="end">{xml_escape(item["name"])}</text>'
            f'<rect x="{bar_left}" y="{y}" width="{length:.1f}" height="14" fill="#1d4e89"/>'
            f'<text x="{bar_left + length + 6:.1f}" y="{y + 12}" font-size="11">{xml_escape(label)}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="XGBoost feature gain">'
        f'<text x="8" y="14" font-size="13">XGBoost feature gain, six-month model</text>'
        f'{"".join(bars)}'
        f"</svg>"
    )


def horizon_svg(horizons: list[dict]) -> str:
    if not horizons:
        return ""
    width, height = 680, 260
    left, right, bottom, top = 56, 20, 40, 48
    plot_bottom = height - bottom
    plot_height = plot_bottom - top
    ticks = [0, 0.25, 0.5, 0.75, 1]
    group = (width - left - right) / len(horizons)
    grid = []
    for tick in ticks:
        y = plot_bottom - plot_height * tick
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e2e2e2"/>'
            f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end">{tick:.2f}</text>'
        )
    bars = []
    for index, row in enumerate(horizons):
        origin = left + index * group
        grid.append(
            f'<line x1="{origin:.1f}" y1="{top}" x2="{origin:.1f}" y2="{plot_bottom}" stroke="#f0f0f0"/>'
        )
        for offset, key, color in ((group * 0.28, "model_score", "#1d4e89"), (group * 0.52, "cadence_score", "#c47b2b")):
            score = row.get(key)
            if score is None:
                continue
            clipped = max(0.0, min(1.0, float(score)))
            bar_h = plot_height * clipped
            x = origin + offset
            y = plot_bottom - bar_h
            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="22" height="{bar_h:.1f}" fill="{color}"/>'
                f'<text x="{x + 11:.1f}" y="{max(top + 12, y - 4):.1f}" font-size="11" text-anchor="middle">{clipped:.2f}</text>'
            )
        bars.append(
            f'<text x="{origin + group / 2:.1f}" y="{height - 16}" font-size="12" text-anchor="middle">{row["months"]} months</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Model and cadence scores">'
        f'<text x="{left}" y="18" font-size="13">Score from 0 to 1, by horizon</text>'
        f'<text x="{left + 250}" y="18" font-size="11" fill="#1d4e89">XGBoost</text>'
        f'<text x="{left + 320}" y="18" font-size="11" fill="#c47b2b">Cadence</text>'
        f'{"".join(grid)}{"".join(bars)}'
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

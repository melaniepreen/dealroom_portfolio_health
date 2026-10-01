"""Explainable alerts. A model score alone does not set severity."""

from __future__ import annotations

from datetime import datetime, timezone

from sentinel.features import cadence, industry_position, target_gaps


def rebuild_alerts(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM alert")
        cur.execute("SELECT * FROM company WHERE in_portfolio")
        companies = list(cur.fetchall())
    for company in companies:
        for alert in _alerts_for(conn, company):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO alert (id, company_id, type, severity, title, summary, evidence, missing, next_step, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                    """,
                    (
                        f"{company['id']}-{alert['type']}",
                        company["id"],
                        alert["type"],
                        alert["severity"],
                        alert["title"],
                        alert["summary"],
                        _json(alert["evidence"]),
                        _json(alert["missing"]),
                        alert["next_step"],
                        datetime.now(timezone.utc),
                    ),
                )
    conn.commit()


def _alerts_for(conn, company: dict) -> list[dict]:
    if not company["found_in_dealroom"]:
        return [
            _alert(
                "DATA_ANOMALY",
                "watch",
                f"No Dealroom record for {company['name']}",
                "The sync did not find this company, so there is no passage to retrieve.",
                [],
                ["dealroom_record"],
                "Confirm the legal name before treating the company as ready to raise.",
            )
        ]
    alerts = []
    clock = cadence(conn, company["id"])
    position = industry_position(conn, company)
    targets = target_gaps(conn, company["id"])
    if clock["own_spacing"] and clock["months_since_last_vc"] and clock["months_since_last_vc"] > clock["own_spacing"]:
        alerts.append(
            _alert(
                "FUNDRAISING_WINDOW",
                "attention",
                f"{company['name']} is past its own venture spacing",
                "Months since the last venture round exceed this company's own gap. Debt is ignored.",
                [{"months_since_last_vc": clock["months_since_last_vc"], "own_spacing": clock["own_spacing"]}],
                [],
                "Discuss financing timing. This is not a decision to lead the round.",
            )
        )
    misses = [row for row in targets["targets"] if row["metric"] != "runway" and row["ratio"] is not None and row["ratio"] < 1]
    if misses:
        alerts.append(
            _alert(
                "TARGET_MISS",
                "attention",
                f"{company['name']} is behind a fund target",
                "A stored Dealroom actual is below the target the fund entered.",
                misses,
                [],
                "Ask the founder which milestone is still open before a raise.",
            )
        )
    runway = [row for row in targets["targets"] if row["metric"] == "runway" and row["target"] is not None and row["target"] < 12]
    if runway:
        alerts.append(
            _alert(
                "FINANCING_PRESSURE",
                "attention",
                f"{company['name']} has a saved runway figure",
                "The fund entered a runway figure. Dealroom does not supply cash or burn, so this uses only that saved figure.",
                runway,
                [] if runway[0]["target"] is not None else ["runway"],
                "Ask how many months of cash remain before discussing a preemptive round.",
            )
        )
    shift = _peer_shift(conn, company["industry_name"])
    if shift is not None:
        alerts.append(
            _alert(
                "PEER_MARKET_SHIFT",
                "watch",
                f"UK {company['industry_name']} venture funding moved",
                "The stored industry venture series moved by more than a quarter over six months. 2026 months are partial.",
                [shift],
                [],
                "Read the company against this industry, not against a sum of industries.",
            )
        )
    early = _early_flags(conn, company, clock, position, misses)
    if len(early) >= 2:
        alerts.append(
            _alert(
                "EARLY_SIGNAL",
                "watch",
                f"Early signs at {company['name']}",
                "More than one current flag is on. The model score did not set this severity.",
                early,
                position["dropped"],
                "Compare the company with competitors before preempting.",
            )
        )
    if position["dropped"]:
        alerts.append(
            _alert(
                "DATA_ANOMALY",
                "info",
                f"Missing series for {company['name']}",
                "Some industry comparisons were dropped because a month was missing.",
                [],
                position["dropped"],
                "Do not read a missing series as zero traction.",
            )
        )
    return alerts


def _early_flags(conn, company: dict, clock: dict, position: dict, misses: list) -> list[str]:
    flags = []
    ratio = position["ratios"].get("employee_growth")
    if ratio is not None and ratio > 1.1:
        flags.append("employees ahead of the industry median")
    elif ratio is not None and ratio < 0.9:
        flags.append("employees behind the industry median")
    if _traffic_up_industry_flat(conn, company):
        flags.append("traffic up while the industry venture series is flat")
    if clock["months_since_last_vc"] and clock["own_spacing"] and clock["months_since_last_vc"] > clock["own_spacing"]:
        flags.append("round gap longer than the company's own spacing")
    if misses:
        flags.append("a fund target is being missed")
    if _stale_valuation(company):
        flags.append("valuation date is stale")
    return flags


def _traffic_up_industry_flat(conn, company: dict) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, traffic FROM monthly_signal
            WHERE company_id = %s AND traffic IS NOT NULL
            ORDER BY year, month
            """,
            (company["id"],),
        )
        points = list(cur.fetchall())
    if len(points) < 2 or not points[0]["traffic"]:
        return False
    if points[-1]["traffic"] <= points[0]["traffic"] * 1.1:
        return False
    start, end = points[0], points[-1]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT vc_funding FROM industry_month
            WHERE industry_name = %s AND year = %s AND month = %s
            """,
            (company["industry_name"], start["year"], start["month"]),
        )
        first = cur.fetchone()
        cur.execute(
            """
            SELECT vc_funding FROM industry_month
            WHERE industry_name = %s AND year = %s AND month = %s
            """,
            (company["industry_name"], end["year"], end["month"]),
        )
        last = cur.fetchone()
    if not first or not last or not first["vc_funding"]:
        return False
    change = abs(last["vc_funding"] - first["vc_funding"]) / first["vc_funding"]
    return change < 0.05


def _stale_valuation(company: dict) -> bool:
    year = company.get("valuation_year")
    month = company.get("valuation_month") or 1
    if not year:
        return False
    from sentinel.portfolio import AS_OF

    return (AS_OF[0] - int(year)) * 12 + (AS_OF[1] - int(month)) > 18


def _peer_shift(conn, industry_name: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT year, month, vc_funding FROM industry_month
            WHERE industry_name = %s AND vc_funding IS NOT NULL
            ORDER BY year, month
            """,
            (industry_name,),
        )
        points = list(cur.fetchall())
    if len(points) < 7 or not points[-7]["vc_funding"]:
        return None
    start = points[-7]["vc_funding"]
    end = points[-1]["vc_funding"]
    change = (end - start) / start
    if abs(change) < 0.25:
        return None
    return {"from": start, "to": end, "change": change}


def _alert(kind, severity, title, summary, evidence, missing, next_step) -> dict:
    return {
        "type": kind,
        "severity": severity,
        "title": title,
        "summary": summary,
        "evidence": evidence,
        "missing": missing,
        "next_step": next_step,
    }


def _json(value) -> str:
    import json

    return json.dumps(value)

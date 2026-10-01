"""Read Dealroom and write the internal company tables."""

from __future__ import annotations

from datetime import datetime, timezone

from sentinel.db import connect, init_schema
from sentinel.dealroom import LiveDealroomProvider
from sentinel.portfolio import PORTFOLIO
from sentinel.store import apply_dealroom_record, apply_industry_points, company_id, mark_not_found, refresh_peer_medians


def sync() -> None:
    provider = LiveDealroomProvider.from_env()
    fetched = datetime.now(timezone.utc)
    with connect() as conn:
        init_schema(conn)
        seen = set()
        for company in PORTFOLIO:
            _sync_portfolio_company(conn, provider, company, fetched)
            seen.add(company["name"].lower())
        for industry in {company["industry"] for company in PORTFOLIO}:
            endpoint, points = provider.industry_funding(industry)
            if points:
                apply_industry_points(conn, industry, points, fetched, endpoint)
        for row in provider.uk_venture_panel():
            name = row.get("name") or ""
            if not name or name.lower() in seen:
                continue
            record = provider.company_record(row["uuid"])
            apply_dealroom_record(
                conn,
                {
                    "name": name,
                    "industry": _industry_name(record) or "Unknown",
                    "in_portfolio": False,
                },
                record,
                fetched,
            )
            seen.add(name.lower())
        refresh_peer_medians(conn)
        conn.commit()


def _sync_portfolio_company(conn, provider: LiveDealroomProvider, company: dict, fetched: datetime) -> None:
    if not company["public"]:
        mark_not_found(conn, company, fetched)
        return
    match = provider.search_company(company["name"])
    if match is None or not match.get("uuid"):
        mark_not_found(conn, company, fetched)
        return
    record = provider.company_record(match["uuid"])
    apply_dealroom_record(conn, {**company, "in_portfolio": True}, record, fetched)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE company SET source_endpoint = %s WHERE id = %s
            """,
            (f"/data/companies/{match['uuid']}", company_id(company["name"])),
        )


def _industry_name(record: dict) -> str | None:
    body = record.get("company") or {}
    for key in ("industries", "industry"):
        value = body.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                return first.get("name")
            return str(first)
        if isinstance(value, dict):
            return value.get("name")
        if isinstance(value, str) and value:
            return value
    return None


if __name__ == "__main__":
    sync()

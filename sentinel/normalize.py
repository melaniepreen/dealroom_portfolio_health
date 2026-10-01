"""Turn Dealroom payloads into company-database rows. Null stays null."""

from __future__ import annotations

from sentinel.portfolio import STAGE_ORDER

_STAGE_ALIASES = {
    "pre-seed": "Pre-Seed",
    "preseed": "Pre-Seed",
    "pre_seed": "Pre-Seed",
    "seed": "Seed",
    "series a": "Series A",
    "series_a": "Series A",
    "series b": "Series B",
    "series_b": "Series B",
    "series c": "Series C",
    "series_c": "Series C",
    "series d": "Series D",
    "series_d": "Series D",
    "series e": "Series E",
    "series_e": "Series E",
    "series f": "Series F+",
    "series_f": "Series F+",
    "series f+": "Series F+",
}


def money(value):
    if isinstance(value, dict):
        return value.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def canonical_stage(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value")
    if not value:
        return None
    text = str(value).strip()
    if text in STAGE_ORDER:
        return text
    return _STAGE_ALIASES.get(text.lower())


def _year_month_from_date(value) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    text = str(value)
    parts = text.replace("/", "-").split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return None, None


def year_month(row: dict) -> tuple[int | None, int | None]:
    year = row.get("year")
    month = row.get("month")
    if year and month:
        return int(year), int(month)
    for key in ("date", "announced_date", "month_date"):
        parsed = _year_month_from_date(row.get(key))
        if parsed[0]:
            return parsed
    if year:
        return int(year), 12
    return None, None


def funding_rounds(rows: list | None) -> list[dict]:
    parsed = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        year, month = year_month(row)
        if not row.get("month") and not any(row.get(k) for k in ("date", "announced_date", "month_date")):
            month = None  # A year-only round cannot establish a monthly outcome.
        amount = money(row.get("amount"))
        if amount is None:
            amount = money(row.get("amount_usd"))
        parsed.append(
            {
                "year": year,
                "month": month,
                "amount": amount,
                "standardized_round": canonical_stage(row.get("standardized_round")),
                "is_vc_round": bool(row.get("is_vc_round")),
            }
        )
    return parsed


def filings(rows: list | None) -> list[dict]:
    parsed = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        year = row.get("year")
        if year is None:
            year, _month = year_month(row)
        if year is None:
            continue
        revenue = money(row.get("revenue"))
        if revenue is None and isinstance(row.get("values"), dict):
            revenue = money(row["values"].get("revenue"))
        employees = money(row.get("employees"))
        if employees is None and isinstance(row.get("values"), dict):
            employees = money(row["values"].get("employees"))
        parsed.append({"year": int(year), "revenue": revenue, "employees": employees})
    return parsed


def traffic_points(rows: list | None) -> list[dict]:
    parsed = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        year, month = year_month(row)
        if year is None or month is None:
            continue
        visits = money(row.get("value"))
        if visits is None:
            visits = money(row.get("visits"))
        if visits is None:
            visits = money(row.get("monthly_visits"))
        parsed.append({"year": year, "month": month, "traffic": visits})
    return parsed


def employee_points_from_headcount(rows: list | None) -> list[dict]:
    """Headcount mix is a share of the team, not a headcount. Shares are not stored as employees."""
    usable = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if any(key in row for key in ("percentage", "share", "percent")):
            continue
        year, month = year_month(row)
        employees = money(row.get("employees") or row.get("value") or row.get("count"))
        if year and month and employees is not None:
            usable.append({"year": year, "month": month, "employees": employees})
    return usable


def founder_rows(rows: list | None) -> list[dict]:
    parsed = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        prior = row.get("founded_companies_count")
        if prior is None:
            prior = row.get("prior_startup_count")
        university = None
        education = row.get("education") or []
        if isinstance(education, list) and education:
            first = education[0] or {}
            if isinstance(first, dict):
                university = first.get("university") or first.get("school") or first.get("name")
        parsed.append(
            {
                "name": row.get("name"),
                "prior_startup_count": None if prior is None else int(prior),
                "university": university,
            }
        )
    return parsed


def current_snapshot(company: dict | None) -> dict:
    body = company or {}
    jobs = body.get("jobs") or {}
    valuation = body.get("valuation") if isinstance(body.get("valuation"), dict) else {}
    year = valuation.get("year")
    month = valuation.get("month")
    if year is None:
        year, month = _year_month_from_date(valuation.get("date"))
    return {
        "jobs_open": jobs.get("open_count"),
        "valuation_year": None if year is None else int(year),
        "valuation_month": None if month is None else int(month),
    }


def timeseries_points(rows) -> list[dict]:
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("items") or []
    parsed = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        year, month = year_month(row)
        value = money(row.get("value"))
        if value is None:
            value = money(row.get("amount"))
        if year and month:
            parsed.append({"year": year, "month": month, "value": value, "partial": int(year) >= 2026})
    return parsed


def hq_country(company: dict | None) -> str | None:
    body = company or {}
    for location in body.get("locations") or []:
        if location.get("role") == "hq":
            country = location.get("country") or {}
            if isinstance(country, dict):
                return country.get("name")
            return str(country) if country else None
    return None

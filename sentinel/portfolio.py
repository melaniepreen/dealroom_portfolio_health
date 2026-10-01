"""The example book. Public names come from the Phoenix Court companies list."""

from __future__ import annotations

AS_OF = (2026, 10)

# industry tag names. Live sync stores whatever Dealroom returns; these are the book labels.
PORTFOLIO = [
    {"name": "Nila", "industry": "Health", "stage_tag": "Pre-Seed", "public": True},
    {"name": "Frontier Computing", "industry": "AI and machine learning", "stage_tag": "Pre-Seed", "public": True},
    {"name": "Grafit", "industry": "Manufacturing and industry", "stage_tag": "Seed", "public": True},
    {"name": "Bron", "industry": "Finance and payments", "stage_tag": "Seed", "public": True},
    {"name": "Catalog", "industry": "Marketplaces", "stage_tag": "Series A", "public": True},
    {"name": "Dexory", "industry": "Business operations", "stage_tag": "Series A", "public": True},
    {"name": "Stealth Climate", "industry": "Climate", "stage_tag": "Pre-Seed", "public": False},
    {"name": "Stealth Deep Tech", "industry": "Deep tech", "stage_tag": "Pre-Seed", "public": False},
    {"name": "Stealth Transport", "industry": "Transportation", "stage_tag": "Pre-Seed", "public": False},
]

STAGE_ORDER = ["Pre-Seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Series E", "Series F+"]


def next_stage(stage: str | None) -> str | None:
    if stage not in STAGE_ORDER:
        return None
    index = STAGE_ORDER.index(stage)
    if index + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[index + 1]


def portfolio_by_name(name: str) -> dict | None:
    key = name.strip().lower()
    for company in PORTFOLIO:
        if company["name"].lower() == key:
            return company
    return None

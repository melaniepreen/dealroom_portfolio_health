"""The example book. Public names come from the Phoenix Court companies list."""

from __future__ import annotations

AS_OF = (2026, 10)

# Domains verified against https://www.phoenixcourt.vc/companies on 2026-10-01.
# industry tag names. Live sync stores whatever Dealroom returns; these are the book labels.
PORTFOLIO = [
    {"name": "Nila", "domain": "nilacares.com", "dealroom_uuid": "d1272c5a-362f-4afd-82f3-1bf16f7baadc", "industry": "Health", "stage_tag": "Pre-Seed", "public": True},
    {"name": "Frontier Computing", "domain": "frontier.site", "dealroom_uuid": "f76c1ca7-944b-4037-9c13-1af0750469ca", "industry": "AI and machine learning", "stage_tag": "Pre-Seed", "public": True},
    {"name": "Grafit", "domain": "grafit.fr", "dealroom_uuid": "f8d75dac-f678-488a-9407-cae0e4a4651f", "industry": "Manufacturing and industry", "stage_tag": "Seed", "public": True},
    {"name": "Bron", "domain": "bron.org", "dealroom_uuid": "1d477e0f-919d-4de0-a03b-ccced3756b02", "industry": "Finance and payments", "stage_tag": "Seed", "public": True},
    {"name": "Catalog", "domain": "startcatalog.com", "dealroom_uuid": "a31ddcd1-b6f6-42de-bef1-f67384034568", "industry": "Marketplaces", "stage_tag": "Series A", "public": True},
    {"name": "Dexory", "domain": "dexory.com", "dealroom_uuid": "b6806b00-6926-4ec6-9586-160aebdd9fd2", "industry": "Business operations", "stage_tag": "Series A", "public": True},
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

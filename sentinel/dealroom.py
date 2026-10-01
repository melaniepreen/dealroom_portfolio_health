"""Dealroom reader. The live adapter is the only place that knows vendor URLs."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

API = "https://api.beta.dealroom.app"
TOKEN_URL = "https://accounts.dealroom.co/oauth/token"
UA = "dealroom-portfolio-health/1.0"


class DealroomProvider(Protocol):
    def search_company(self, name: str) -> dict | None: ...

    def company_record(self, uuid: str) -> dict: ...


@dataclass
class LiveDealroomProvider:
    client_id: str
    client_secret: str
    _token: str = ""
    _expires_at: float = 0

    @classmethod
    def from_env(cls) -> "LiveDealroomProvider":
        client_id = os.environ.get("DEALROOM_CLIENT_ID", "")
        client_secret = os.environ.get("DEALROOM_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise RuntimeError("DEALROOM_CLIENT_ID and DEALROOM_CLIENT_SECRET are required to sync.")
        return cls(client_id=client_id, client_secret=client_secret)

    def _token_value(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        body = json.dumps(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "audience": API,
                "grant_type": "client_credentials",
            }
        ).encode()
        request = urllib.request.Request(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": UA},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
        self._token = payload["access_token"]
        self._expires_at = time.time() + int(payload["expires_in"])
        return self._token

    def get(self, path: str) -> dict | list:
        request = urllib.request.Request(
            API + path,
            headers={
                "Authorization": f"Bearer {self._token_value()}",
                "X-Client-Id": self.client_id,
                "User-Agent": UA,
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:500]
            raise RuntimeError(f"Dealroom {exc.code} for {path}: {detail}") from exc

    def search_company(self, name: str) -> dict | None:
        payload = self.get("/data/search?" + urllib.parse.urlencode({"q": name, "limit": "5"}))
        rows = payload.get("data") if isinstance(payload, dict) else []
        for row in rows or []:
            if str(row.get("name", "")).lower() == name.lower() and row.get("type") == "company":
                return row
        return None

    def company_record(self, uuid: str) -> dict:
        company = self.get(f"/data/companies/{uuid}")
        rounds = self.get(f"/data/companies/{uuid}/funding-rounds?limit=100")
        financials = self._optional(f"/data/companies/{uuid}/financials")
        traffic = self._optional(f"/data/companies/{uuid}/web-traffic")
        team = self._optional(f"/data/companies/{uuid}/team?limit=20")
        headcount = self._optional(f"/data/companies/{uuid}/headcount-breakdown")
        return {
            "company": company.get("data") if isinstance(company, dict) else company,
            "rounds": rounds.get("data") if isinstance(rounds, dict) else [],
            "financials": financials.get("data") if isinstance(financials, dict) else [],
            "traffic": traffic.get("data") if isinstance(traffic, dict) else [],
            "team": team.get("data") if isinstance(team, dict) else [],
            "headcount": headcount.get("data") if isinstance(headcount, dict) else [],
        }

    def resolve_industry_id(self, industry_name: str) -> int | None:
        """Prefer the industry family (id ending in 03) over a same-named sector tag."""
        payload = self.get("/data/search?" + urllib.parse.urlencode({"q": industry_name, "limit": "20"}))
        rows = payload.get("data") if isinstance(payload, dict) else []
        fallback = None
        for row in rows or []:
            ident = row.get("taxonomy_id") or row.get("id")
            try:
                ident = int(ident)
            except (TypeError, ValueError):
                continue
            type_name = str(row.get("type") or "").lower()
            row_name = str(row.get("name") or "")
            industry_family = ident % 100 == 3 or type_name == "industry"
            if not industry_family or type_name == "sector":
                continue
            if row_name.lower() == industry_name.lower():
                return ident
            if industry_name.lower() in row_name.lower():
                fallback = ident
        return fallback

    def industry_funding(self, industry_name: str) -> tuple[str, list]:
        """UK HQ venture funding for one industry tag. Empty when the tag cannot be resolved."""
        taxonomy_id = self.resolve_industry_id(industry_name)
        if taxonomy_id is None:
            return "", []
        filt = urllib.parse.quote(
            "and("
            "locations[country=United Kingdom][role=hq],"
            "is_vc_round[eq]:true,"
            "growth_stage[nin_any]:412,"
            "taxonomy_id[nin_any]:1102801,"
            f"taxonomy_id[in_any]:{taxonomy_id}"
            ")"
        )
        path = f"/analytics/timeseries?metric=vc_funding&filter={filt}"
        try:
            payload = self.get(path)
        except RuntimeError:
            return path, []
        rows = payload.get("data") if isinstance(payload, dict) else []
        return path, rows or []

    def uk_venture_panel(self, limit: int = 24) -> list[dict]:
        """A UK venture-backed panel wider than the nine holdings. HQ is checked on each row."""
        filt = urllib.parse.quote(
            "and(classification[in_any]:vc_backed,growth_stage[nin_any]:412,taxonomy_id[nin_any]:1102801)"
        )
        path = f"/data/companies?limit={limit}&filter={filt}"
        try:
            payload = self.get(path)
        except RuntimeError:
            return []
        rows = payload.get("data") if isinstance(payload, dict) else []
        kept = []
        for row in rows or []:
            country = ""
            for location in row.get("locations") or []:
                if location.get("role") == "hq":
                    value = location.get("country") or {}
                    country = value.get("name") if isinstance(value, dict) else str(value or "")
            if country == "United Kingdom" and row.get("uuid"):
                kept.append(row)
        return kept

    def _optional(self, path: str):
        try:
            return self.get(path)
        except RuntimeError:
            return {"data": []}

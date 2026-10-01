"""Dealroom reader. The live adapter is the only place that knows vendor URLs."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
import threading
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
    _request_lock: object = field(default_factory=threading.Lock, repr=False)
    _last_request: float = 0

    @classmethod
    def from_env(cls) -> "LiveDealroomProvider":
        # Load the existing local credentials without printing or rewriting them.
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
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
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        self._token = payload["access_token"]
        self._expires_at = time.time() + int(payload["expires_in"])
        return self._token

    def get(self, path: str) -> dict | list:
        cache = Path('.dealroom-cache') / (hashlib.sha256(path.encode()).hexdigest() + '.json')
        if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
            return json.loads(cache.read_text())["response"]
        request = urllib.request.Request(
            API + path,
            headers={
                "Authorization": f"Bearer {self._token_value()}",
                "X-Client-Id": self.client_id,
                "User-Agent": UA,
            },
        )
        for attempt in range(4):
            with self._request_lock:
                time.sleep(max(0, .26 - (time.monotonic() - self._last_request)))
                self._last_request = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=40) as response:
                    payload = json.load(response)
                cache.parent.mkdir(exist_ok=True)
                cache.write_text(json.dumps({"path": path, "fetched_at": time.time(), "response": payload}))
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    self._token = ""
                    request.add_header("Authorization", f"Bearer {self._token_value()}")
                    continue
                if exc.code == 429 or exc.code >= 500:
                    time.sleep(min(30, float(exc.headers.get('Retry-After') or 2 ** attempt)))
                    continue
                detail = exc.read().decode()[:500]
                raise RuntimeError(f"Dealroom {exc.code} for {path}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Dealroom retries exhausted for {path}")

    def funding_history(self, uuid: str) -> list:
        rows, cursor = [], None
        while True:
            query = {"limit": 100}
            if cursor:
                query["cursor"] = cursor
            payload = self.get(f"/data/companies/{uuid}/funding-rounds?" + urllib.parse.urlencode(query))
            rows.extend(payload.get("data") or [])
            nxt = (payload.get("page") or {}).get("next_cursor")
            if not nxt:
                return rows
            if nxt == cursor:
                raise RuntimeError('Funding pagination did not advance')
            cursor = nxt

    def search_company(self, name: str, domain: str | None = None) -> dict | None:
        payload = self.get("/data/search?" + urllib.parse.urlencode({"q": name, "limit": "20", "types": "company"}))
        rows = payload.get("data") if isinstance(payload, dict) else []
        matches = [row for row in rows or [] if str(row.get("name", "")).lower() == name.lower() and row.get("type") == "company"]
        if domain:
            matches = [row for row in rows or [] if str(row.get("website_domain") or "").lower().removeprefix("www.") == domain.lower().removeprefix("www.")]
        return matches[0] if len(matches) == 1 else None

    def company_record(self, uuid: str) -> dict:
        company = self.get(f"/data/companies/{uuid}")
        rounds = self.funding_history(uuid)
        financials = self._optional(f"/data/companies/{uuid}/financials")
        traffic = self._optional(f"/data/companies/{uuid}/web-traffic")
        team = self._optional(f"/data/companies/{uuid}/team?limit=20")
        headcount = self._optional(f"/data/companies/{uuid}/headcount-breakdown")
        return {
            "company": company.get("data") if isinstance(company, dict) else company,
            "rounds": rounds,
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
        """A UK venture-backed panel wider than the six holdings. HQ is checked on each row."""
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

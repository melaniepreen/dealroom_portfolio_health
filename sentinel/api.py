"""Local page, REST, and MCP. OpenAI is optional."""

from __future__ import annotations

from contextlib import asynccontextmanager
from html import escape

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from sentinel.db import connect, init_schema
from sentinel.fixture import load_fixture
from sentinel.pipeline import prepare
from sentinel.portfolio import PORTFOLIO
from sentinel.tools import TOOL_NAMES, dispatch, dumps


def startup() -> None:
    with connect() as conn:
        init_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM company")
            count = cur.fetchone()["n"]
        if count == 0:
            load_fixture(conn)
            prepare(conn)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield


app = FastAPI(title="Portfolio Sentinel", lifespan=lifespan)


def _call(name: str, arguments: dict):
    try:
        with connect() as conn:
            return dispatch(conn, name, arguments)
    except KeyError:
        raise HTTPException(status_code=404, detail="Company not in the portfolio.") from None


@app.get("/", response_class=HTMLResponse)
def home(company: str = "Nila"):
    brief = _call("generate_company_brief", {"company": company})
    options = "".join(
        f'<option value="{item["name"]}" {"selected" if item["name"] == company else ""}>{item["name"]}</option>'
        for item in PORTFOLIO
    )
    signal = brief["readiness"]
    question = escape(str(brief["question"]))
    next_stage = escape(str(signal.get("next_stage") or "unknown"))
    note = escape(str(signal.get("note") or ""))
    step = escape(str(brief["next_step"]))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Portfolio Sentinel</title></head>
<body>
<h1>Should I preempt this raise?</h1>
<form method="get"><label>Company <select name="company">{options}</select></label>
<button type="submit">Look up</button></form>
<p>{question}</p>
<p>Next stage: {next_stage}. Six-month model score: {signal.get("model_score_6m")}. Cadence score: {signal.get("cadence_score_6m")}.</p>
<p>{note}</p>
{brief.get("graph_svg") or ""}
<p>Solid line is the company. Dashed line is the competitor median in the same industry.</p>
<p>{step}</p>
</body></html>"""


@app.get("/alerts")
def alerts():
    return _call("get_portfolio_alerts", {})


@app.get("/companies/{name}/changes")
def changes(name: str, lookback: int = 6):
    return _call("get_company_changes", {"company": name, "lookback": lookback})


@app.get("/companies/{name}/prediction")
def prediction(name: str):
    return _call("get_company_prediction", {"company": name})


@app.get("/companies/{name}/industry")
def industry(name: str):
    return _call("get_industry_position", {"company": name})


@app.get("/companies/{name}/targets")
def targets(name: str):
    return _call("get_company_targets", {"company": name})


@app.get("/companies/{name}/brief")
def brief(name: str):
    return _call("generate_company_brief", {"company": name})


@app.get("/retrieve")
def retrieve(q: str):
    return _call("retrieve_context", {"query": q})


@app.post("/mcp")
def mcp(body: dict):
    method = body.get("method")
    request_id = body.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "portfolio-sentinel", "version": "0.1.0"},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in TOOL_NAMES]},
        }
    if method == "tools/call":
        params = body.get("params") or {}
        try:
            payload = _call(params.get("name"), params.get("arguments") or {})
        except HTTPException as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": 404, "message": exc.detail}}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": dumps(payload)}]},
        }
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}

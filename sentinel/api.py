"""Local page, REST, and MCP. OpenAI is optional."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from sentinel.db import connect, init_schema
from sentinel.dashboard import portfolio_dashboard
from sentinel.tools import TOOL_NAMES, dispatch, dumps


def startup() -> None:
    with connect() as conn:
        init_schema(conn)



@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield


app = FastAPI(title="XYZ Capital · Portfolio", lifespan=lifespan)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _call(name: str, arguments: dict):
    try:
        with connect() as conn:
            return dispatch(conn, name, arguments)
    except KeyError:
        raise HTTPException(status_code=404, detail="Company not in the portfolio.") from None


@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/portfolio")
def portfolio(horizon: int = Query(3, ge=3, le=6)):
    if horizon not in (3, 6):
        raise HTTPException(status_code=422, detail="Choose 3 or 6 months.")
    with connect() as conn:
        return portfolio_dashboard(conn, horizon)


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

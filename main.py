"""Bankroll V2.2 API-Football gateway + ChatGPT OAuth MCP.

Drop-in replacement for the repository's app/main.py. Existing gateway/bridge
routes and all nine MCP tools are preserved. OAuth mode is fail-closed and
uses an external OAuth 2.1 authorization server. No secrets are hard-coded.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "").strip()
CHATGPT_BRIDGE_TOKEN = os.getenv("CHATGPT_BRIDGE_TOKEN", "").strip()
CHATGPT_MCP_TOKEN = (os.getenv("CHATGPT_MCP_TOKEN", "").strip() or CHATGPT_BRIDGE_TOKEN)
DAILY_LIMIT = int(os.getenv("API_DAILY_LIMIT", "90"))
BASE_URL = os.getenv("API_FOOTBALL_BASE_URL", "https://v3.football.api-sports.io").rstrip("/")
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
DB_PATH = os.getenv("DB_PATH", "data/gateway.db")

MCP_AUTH_MODE = os.getenv("MCP_AUTH_MODE", "legacy").strip().lower()
if MCP_AUTH_MODE not in {"legacy", "oauth"}:
    raise RuntimeError("MCP_AUTH_MODE must be 'legacy' or 'oauth'")

MCP_OAUTH_CONFIG: dict[str, str] | None = None
MCP_SERVER_AUTH_KWARGS: dict[str, Any] = {}
if MCP_AUTH_MODE == "oauth":
    from app.mcp_oauth import create_oauth_options, protected_resource_metadata
    MCP_OAUTH_CONFIG, MCP_SERVER_AUTH_KWARGS = create_oauth_options()

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
app = FastAPI(title="Bankroll Engine V2.2 API-Football Gateway", version="1.2.0")


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.execute("CREATE TABLE IF NOT EXISTS cache(cache_key TEXT PRIMARY KEY,created INTEGER,payload TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY,requests INTEGER)")
    connection.commit()
    return connection


def day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def usage() -> int:
    connection = db()
    row = connection.execute("SELECT requests FROM usage WHERE day=?", (day(),)).fetchone()
    connection.close()
    return row[0] if row else 0


def auth(token: str | None):
    if not GATEWAY_TOKEN:
        raise HTTPException(status_code=500, detail="GATEWAY_TOKEN is not configured")
    if token != GATEWAY_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid gateway token")


def bridge_auth(token: str):
    if not CHATGPT_BRIDGE_TOKEN:
        raise HTTPException(status_code=500, detail="CHATGPT_BRIDGE_TOKEN is not configured")
    if token != CHATGPT_BRIDGE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid ChatGPT bridge token")


async def get_api(path: str, params: dict[str, Any]):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API_FOOTBALL_KEY is not configured")
    params = {key: value for key, value in params.items() if value is not None and value != ""}
    cache_key = path + "?" + json.dumps(params, sort_keys=True)
    connection = db()
    cached_row = connection.execute("SELECT created,payload FROM cache WHERE cache_key=?", (cache_key,)).fetchone()
    connection.close()
    if cached_row and time.time() - cached_row[0] < CACHE_TTL:
        return json.loads(cached_row[1]), True
    if usage() >= DAILY_LIMIT:
        raise HTTPException(status_code=429, detail=f"API daily safety limit reached: {DAILY_LIMIT}")
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(BASE_URL + path, params=params, headers={"x-apisports-key": API_KEY})
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:500])
    payload = response.json()
    connection = db()
    connection.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (cache_key, int(time.time()), json.dumps(payload)))
    connection.execute("INSERT INTO usage(day,requests) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET requests=requests+1", (day(),))
    connection.commit()
    connection.close()
    return payload, False


def out(payload: Any, cached: bool):
    return {"cached": cached, "usage_today": usage(), "daily_safety_limit": DAILY_LIMIT, "data": payload}


@app.get("/health")
async def health():
    return {
        "ok": True,
        "api_key_configured": bool(API_KEY),
        "gateway_auth_configured": bool(GATEWAY_TOKEN),
        "mcp_configured": MCP_AUTH_MODE == "oauth" or bool(CHATGPT_MCP_TOKEN),
        "mcp_auth_mode": MCP_AUTH_MODE,
        "usage_today": usage(),
        "daily_safety_limit": DAILY_LIMIT,
    }


@app.get("/api/status")
async def status(x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    return {"api_football": bool(API_KEY), "usage_today": usage(), "daily_safety_limit": DAILY_LIMIT,
            "mcp_configured": MCP_AUTH_MODE == "oauth" or bool(CHATGPT_MCP_TOKEN)}


@app.get("/fixtures")
async def fixtures(date: Optional[str] = None, league: Optional[int] = None,
                   season: Optional[int] = None, team: Optional[int] = None,
                   fixture: Optional[int] = None, status: Optional[str] = None,
                   x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    payload, cached = await get_api("/fixtures", {"date": date, "league": league, "season": season,
                                                  "team": team, "id": fixture, "status": status})
    return out(payload, cached)


@app.get("/fixtures/{fixture_id}/statistics")
async def statistics(fixture_id: int, x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    payload, cached = await get_api("/fixtures/statistics", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/fixtures/{fixture_id}/lineups")
async def lineups(fixture_id: int, x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    payload, cached = await get_api("/fixtures/lineups", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/fixtures/{fixture_id}/injuries")
async def injuries(fixture_id: int, x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    payload, cached = await get_api("/injuries", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/fixtures/{fixture_id}/predictions")
async def predictions(fixture_id: int, x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    payload, cached = await get_api("/predictions", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/fixtures/{fixture_id}/odds")
async def odds(fixture_id: int, x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    payload, cached = await get_api("/odds", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/h2h")
async def h2h(h2h: str, last: int = 10, x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    payload, cached = await get_api("/fixtures/headtohead", {"h2h": h2h, "last": last})
    return out(payload, cached)


@app.get("/teams/{team_id}/statistics")
async def team_stats(team_id: int, league: int, season: int, x_gateway_token: Optional[str] = Header(None)):
    auth(x_gateway_token)
    payload, cached = await get_api("/teams/statistics", {"team": team_id, "league": league, "season": season})
    return out(payload, cached)


@app.get("/chat/{bridge_token}/fixtures")
async def chat_fixtures(bridge_token: str, date: Optional[str] = None, league: Optional[int] = None,
                        season: Optional[int] = None, team: Optional[int] = None,
                        fixture: Optional[int] = None, status: Optional[str] = None):
    bridge_auth(bridge_token)
    payload, cached = await get_api("/fixtures", {"date": date, "league": league, "season": season,
                                                  "team": team, "id": fixture, "status": status})
    return out(payload, cached)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/statistics")
async def chat_statistics(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    payload, cached = await get_api("/fixtures/statistics", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/lineups")
async def chat_lineups(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    payload, cached = await get_api("/fixtures/lineups", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/injuries")
async def chat_injuries(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    payload, cached = await get_api("/injuries", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/predictions")
async def chat_predictions(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    payload, cached = await get_api("/predictions", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/odds")
async def chat_odds(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    payload, cached = await get_api("/odds", {"fixture": fixture_id})
    return out(payload, cached)


@app.get("/chat/{bridge_token}/h2h")
async def chat_h2h(bridge_token: str, h2h: str, last: int = 10):
    bridge_auth(bridge_token)
    payload, cached = await get_api("/fixtures/headtohead", {"h2h": h2h, "last": last})
    return out(payload, cached)


@app.get("/chat/{bridge_token}/teams/{team_id}/statistics")
async def chat_team_stats(bridge_token: str, team_id: int, league: int, season: int):
    bridge_auth(bridge_token)
    payload, cached = await get_api("/teams/statistics", {"team": team_id, "league": league, "season": season})
    return out(payload, cached)


# ----- Read-only MCP endpoint -----
mcp = MCPServer(
    "Bankroll Engine V2.2 API-Football",
    instructions=("Read-only API-Football data for Bankroll Engine. "
                  "API results=0 means NO_DATA. Do not invent observations or odds. "
                  "API predictions are context, not a betting decision."),
    **MCP_SERVER_AUTH_KWARGS,
)


async def _mcp_call(path: str, params: dict[str, Any]):
    payload, cached = await get_api(path, params)
    return out(payload, cached)


@mcp.tool()
async def get_fixtures(date: str | None = None, league: int | None = None, season: int | None = None,
                       team: int | None = None, fixture_id: int | None = None, status: str | None = None) -> dict[str, Any]:
    """Get API-Football fixtures by date, league, season, team or fixture ID."""
    return await _mcp_call("/fixtures", {"date": date, "league": league, "season": season,
                                         "team": team, "id": fixture_id, "status": status})


@mcp.tool()
async def get_fixture_statistics(fixture_id: int) -> dict[str, Any]:
    """Get API-Football fixture statistics."""
    return await _mcp_call("/fixtures/statistics", {"fixture": fixture_id})


@mcp.tool()
async def get_lineups(fixture_id: int) -> dict[str, Any]:
    """Get fixture lineups, substitutes, formations and coaches."""
    return await _mcp_call("/fixtures/lineups", {"fixture": fixture_id})


@mcp.tool()
async def get_injuries(fixture_id: int) -> dict[str, Any]:
    """Get fixture injuries. Empty response means NO_DATA."""
    return await _mcp_call("/injuries", {"fixture": fixture_id})


@mcp.tool()
async def get_fixture_prediction(fixture_id: int) -> dict[str, Any]:
    """Get API-Football prediction input for one fixture."""
    return await _mcp_call("/predictions", {"fixture": fixture_id})


@mcp.tool()
async def get_fixture_odds(fixture_id: int) -> dict[str, Any]:
    """Get API-Football bookmaker odds for a fixture."""
    return await _mcp_call("/odds", {"fixture": fixture_id})


@mcp.tool()
async def get_h2h(h2h: str, last: int = 10) -> dict[str, Any]:
    """Get API-Football head-to-head information."""
    return await _mcp_call("/fixtures/headtohead", {"h2h": h2h, "last": last})


@mcp.tool()
async def get_team_statistics(team_id: int, league: int, season: int) -> dict[str, Any]:
    """Get football team stats by league and season."""
    return await _mcp_call("/teams/statistics", {"team": team_id, "league": league, "season": season})


@mcp.tool()
def get_gateway_usage() -> dict[str, int]:
    """Read gateway request quota without spending an upstream request."""
    return {"usage_today": usage(), "daily_safety_limit": DAILY_LIMIT}


class MCPBearerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not CHATGPT_MCP_TOKEN:
            return JSONResponse({"error": "CHATGPT_MCP_TOKEN is not configured"}, status_code=503)
        if request.headers.get("authorization", "") != f"Bearer {CHATGPT_MCP_TOKEN}":
            return JSONResponse({"error": "Invalid MCP bearer token"}, status_code=401)
        return await call_next(request)


if MCP_AUTH_MODE == "oauth":
    # Root-hosted protected-resource discovery; distinct from the mounted MCP app.
    @app.get("/.well-known/oauth-protected-resource")
    @app.get("/.well-known/oauth-protected-resource/mcp")
    async def mcp_oauth_resource_metadata():
        assert MCP_OAUTH_CONFIG is not None
        return protected_resource_metadata(MCP_OAUTH_CONFIG)


transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["bankroll-v22.onrender.com", "bankroll-v22-api-football-gateway.onrender.com"],
    allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
)
mcp_http_app = mcp.streamable_http_app(
    streamable_http_path="/", json_response=True, stateless_http=True,
    transport_security=transport_security,
)
if MCP_AUTH_MODE == "legacy":
    mcp_http_app.add_middleware(MCPBearerMiddleware)


@contextlib.asynccontextmanager
async def lifespan(_application):
    async with mcp.session_manager.run():
        yield


app.router.lifespan_context = lifespan
app.mount("/mcp", mcp_http_app)

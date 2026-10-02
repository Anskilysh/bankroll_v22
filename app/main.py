import contextlib
import json
import os
import sqlite3
import time
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

load_dotenv()

API_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "").strip()
CHATGPT_BRIDGE_TOKEN = os.getenv("CHATGPT_BRIDGE_TOKEN", "").strip()
# Dedicated token for the ChatGPT MCP connector. If it is not set,
# the existing bridge token is used as a backwards-compatible fallback.
CHATGPT_MCP_TOKEN = (
    os.getenv("CHATGPT_MCP_TOKEN", "").strip() or CHATGPT_BRIDGE_TOKEN
)

DAILY_LIMIT = int(os.getenv("API_DAILY_LIMIT", "90"))
BASE_URL = os.getenv(
    "API_FOOTBALL_BASE_URL",
    "https://v3.football.api-sports.io",
).rstrip("/")
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))
DB_PATH = os.getenv("DB_PATH", "data/gateway.db")

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

app = FastAPI(
    title="Bankroll Engine V2.2 API-Football Gateway",
    version="1.1.0",
)


def db():
    c = sqlite3.connect(DB_PATH)
    c.execute(
        "CREATE TABLE IF NOT EXISTS cache("
        "cache_key TEXT PRIMARY KEY,created INTEGER,payload TEXT)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS usage("
        "day TEXT PRIMARY KEY,requests INTEGER)"
    )
    c.commit()
    return c


def day():
    return time.strftime("%Y-%m-%d", time.gmtime())


def usage():
    c = db()
    r = c.execute(
        "SELECT requests FROM usage WHERE day=?", (day(),)
    ).fetchone()
    c.close()
    return r[0] if r else 0


def auth(token):
    if not GATEWAY_TOKEN:
        raise HTTPException(500, "GATEWAY_TOKEN is not configured")
    if token != GATEWAY_TOKEN:
        raise HTTPException(401, "Invalid gateway token")


async def get_api(path, params):
    if not API_KEY:
        raise HTTPException(500, "API_FOOTBALL_KEY is not configured")

    params = {k: v for k, v in params.items() if v not in (None, "")}
    key = path + "?" + json.dumps(params, sort_keys=True)

    c = db()
    r = c.execute(
        "SELECT created,payload FROM cache WHERE cache_key=?", (key,)
    ).fetchone()
    c.close()

    if r and time.time() - r[0] < CACHE_TTL:
        return json.loads(r[1]), True

    if usage() >= DAILY_LIMIT:
        raise HTTPException(
            429,
            f"API daily safety limit reached: {DAILY_LIMIT}",
        )

    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.get(
            BASE_URL + path,
            params=params,
            headers={"x-apisports-key": API_KEY},
        )

    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text[:500])

    data = resp.json()

    c = db()
    c.execute(
        "INSERT OR REPLACE INTO cache VALUES(?,?,?)",
        (key, int(time.time()), json.dumps(data)),
    )
    c.execute(
        """INSERT INTO usage(day,requests) VALUES(?,1)
           ON CONFLICT(day) DO UPDATE SET requests=requests+1""",
        (day(),),
    )
    c.commit()
    c.close()

    return data, False


def out(data, cached):
    return {
        "cached": cached,
        "usage_today": usage(),
        "daily_safety_limit": DAILY_LIMIT,
        "data": data,
    }


def bridge_auth(token):
    if not CHATGPT_BRIDGE_TOKEN:
        raise HTTPException(
            500, "CHATGPT_BRIDGE_TOKEN is not configured"
        )
    if token != CHATGPT_BRIDGE_TOKEN:
        raise HTTPException(401, "Invalid ChatGPT bridge token")


# ---------------------------------------------------------------------------
# Existing read-only ChatGPT bridge endpoints
# ---------------------------------------------------------------------------

@app.get("/chat/{bridge_token}/fixtures")
async def chat_fixtures(
    bridge_token: str,
    date: Optional[str] = None,
    league: Optional[int] = None,
    season: Optional[int] = None,
    team: Optional[int] = None,
    fixture: Optional[int] = None,
    status: Optional[str] = None,
):
    bridge_auth(bridge_token)
    d, c = await get_api(
        "/fixtures",
        {
            "date": date,
            "league": league,
            "season": season,
            "team": team,
            "id": fixture,
            "status": status,
        },
    )
    return out(d, c)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/statistics")
async def chat_statistics(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    d, c = await get_api(
        "/fixtures/statistics", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/lineups")
async def chat_lineups(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    d, c = await get_api(
        "/fixtures/lineups", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/injuries")
async def chat_injuries(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    d, c = await get_api(
        "/injuries", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/predictions")
async def chat_predictions(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    d, c = await get_api(
        "/predictions", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/chat/{bridge_token}/fixtures/{fixture_id}/odds")
async def chat_odds(bridge_token: str, fixture_id: int):
    bridge_auth(bridge_token)
    d, c = await get_api(
        "/odds", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/chat/{bridge_token}/h2h")
async def chat_h2h(
    bridge_token: str,
    h2h: str,
    last: int = 10,
):
    bridge_auth(bridge_token)
    d, c = await get_api(
        "/fixtures/headtohead",
        {"h2h": h2h, "last": last},
    )
    return out(d, c)


@app.get("/chat/{bridge_token}/teams/{team_id}/statistics")
async def chat_team_stats(
    bridge_token: str,
    team_id: int,
    league: int,
    season: int,
):
    bridge_auth(bridge_token)
    d, c = await get_api(
        "/teams/statistics",
        {"team": team_id, "league": league, "season": season},
    )
    return out(d, c)


# ---------------------------------------------------------------------------
# Existing gateway endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "ok": True,
        "api_key_configured": bool(API_KEY),
        "gateway_auth_configured": bool(GATEWAY_TOKEN),
        "mcp_configured": bool(CHATGPT_MCP_TOKEN),
        "usage_today": usage(),
        "daily_safety_limit": DAILY_LIMIT,
    }


@app.get("/api/status")
async def status(
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    return {
        "api_football": bool(API_KEY),
        "usage_today": usage(),
        "daily_safety_limit": DAILY_LIMIT,
        "mcp_configured": bool(CHATGPT_MCP_TOKEN),
    }


@app.get("/fixtures")
async def fixtures(
    date: Optional[str] = None,
    league: Optional[int] = None,
    season: Optional[int] = None,
    team: Optional[int] = None,
    fixture: Optional[int] = None,
    status: Optional[str] = None,
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    d, c = await get_api(
        "/fixtures",
        {
            "date": date,
            "league": league,
            "season": season,
            "team": team,
            "id": fixture,
            "status": status,
        },
    )
    return out(d, c)


@app.get("/fixtures/{fixture_id}/statistics")
async def statistics(
    fixture_id: int,
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    d, c = await get_api(
        "/fixtures/statistics", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/fixtures/{fixture_id}/lineups")
async def lineups(
    fixture_id: int,
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    d, c = await get_api(
        "/fixtures/lineups", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/fixtures/{fixture_id}/injuries")
async def injuries(
    fixture_id: int,
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    d, c = await get_api(
        "/injuries", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/fixtures/{fixture_id}/predictions")
async def predictions(
    fixture_id: int,
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    d, c = await get_api(
        "/predictions", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/fixtures/{fixture_id}/odds")
async def odds(
    fixture_id: int,
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    d, c = await get_api(
        "/odds", {"fixture": fixture_id}
    )
    return out(d, c)


@app.get("/h2h")
async def h2h(
    h2h: str,
    last: int = 10,
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    d, c = await get_api(
        "/fixtures/headtohead",
        {"h2h": h2h, "last": last},
    )
    return out(d, c)


@app.get("/teams/{team_id}/statistics")
async def team_stats(
    team_id: int,
    league: int,
    season: int,
    x_gateway_token: Optional[str] = Header(None),
):
    auth(x_gateway_token)
    d, c = await get_api(
        "/teams/statistics",
        {"team": team_id, "league": league, "season": season},
    )
    return out(d, c)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = MCPServer(
    "Bankroll Engine V2.2 API-Football",
    instructions=(
        "Read-only API-Football data source for Bankroll Engine V2.2 "
        "and V2.3. Use only data that is actually returned. "
        "results=0 means NO_DATA, not proof that the event has no such data. "
        "API-Football predictions are an input signal, not the final "
        "betting decision. Exact verified Fonbet/BetBoom odds have priority "
        "when separately available."
    ),
)


async def _mcp_call(path: str, params: dict[str, Any]):
    data, cached = await get_api(path, params)
    return {
        "cached": cached,
        "usage_today": usage(),
        "daily_safety_limit": DAILY_LIMIT,
        "data": data,
    }


@mcp.tool()
async def get_fixtures(
    date: str | None = None,
    league: int | None = None,
    season: int | None = None,
    team: int | None = None,
    fixture_id: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Get API-Football fixtures by date, league, season, team or fixture ID."""
    return await _mcp_call(
        "/fixtures",
        {
            "date": date,
            "league": league,
            "season": season,
            "team": team,
            "id": fixture_id,
            "status": status,
        },
    )


@mcp.tool()
async def get_fixture_statistics(
    fixture_id: int,
) -> dict[str, Any]:
    """Get statistics for one API-Football fixture."""
    return await _mcp_call(
        "/fixtures/statistics",
        {"fixture": fixture_id},
    )


@mcp.tool()
async def get_lineups(
    fixture_id: int,
) -> dict[str, Any]:
    """Get lineups, formations, coaches and substitutes for one fixture."""
    return await _mcp_call(
        "/fixtures/lineups",
        {"fixture": fixture_id},
    )


@mcp.tool()
async def get_injuries(
    fixture_id: int,
) -> dict[str, Any]:
    """Get injury data for one fixture. Empty results are NO_DATA."""
    return await _mcp_call(
        "/injuries",
        {"fixture": fixture_id},
    )


@mcp.tool()
async def get_fixture_prediction(
    fixture_id: int,
) -> dict[str, Any]:
    """Get API-Football prediction/form data for one fixture."""
    return await _mcp_call(
        "/predictions",
        {"fixture": fixture_id},
    )


@mcp.tool()
async def get_fixture_odds(
    fixture_id: int,
) -> dict[str, Any]:
    """Get bookmaker odds and available markets for one fixture."""
    return await _mcp_call(
        "/odds",
        {"fixture": fixture_id},
    )


@mcp.tool()
async def get_h2h(
    h2h: str,
    last: int = 10,
) -> dict[str, Any]:
    """Get API-Football head-to-head data. Upstream plan restrictions are returned as-is."""
    return await _mcp_call(
        "/fixtures/headtohead",
        {"h2h": h2h, "last": last},
    )


@mcp.tool()
async def get_team_statistics(
    team_id: int,
    league: int,
    season: int,
) -> dict[str, Any]:
    """Get API-Football season statistics for a team."""
    return await _mcp_call(
        "/teams/statistics",
        {
            "team": team_id,
            "league": league,
            "season": season,
        },
    )


@mcp.tool()
def get_gateway_usage() -> dict[str, int]:
    """Get current gateway quota without consuming an API-Football request."""
    return {
        "usage_today": usage(),
        "daily_safety_limit": DAILY_LIMIT,
    }


class MCPBearerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not CHATGPT_MCP_TOKEN:
            return JSONResponse(
                {"error": "CHATGPT_MCP_TOKEN is not configured"},
                status_code=503,
            )

        authorization = request.headers.get("authorization", "")
        if authorization != f"Bearer {CHATGPT_MCP_TOKEN}":
            return JSONResponse(
                {"error": "Invalid MCP bearer token"},
                status_code=401,
            )

        return await call_next(request)


mcp_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "bankroll-v22.onrender.com",
        "bankroll-v22-api-football-gateway.onrender.com",
    ],
    allowed_origins=[
        "https://chatgpt.com",
        "https://chat.openai.com",
    ],
)

# The MCP app is mounted at /mcp by FastAPI, therefore the MCP transport
# itself uses "/" as its local route.
mcp_http_app = mcp.streamable_http_app(
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
    transport_security=mcp_transport_security,
)
mcp_http_app.add_middleware(MCPBearerMiddleware)

# When an MCP app is mounted into an existing ASGI application, the host
# application must own the MCP session-manager lifespan.
@contextlib.asynccontextmanager
async def lifespan(_application):
    async with mcp.session_manager.run():
        yield


# FastAPI's lifespan is replaced after construction so the existing routes
# remain unchanged.
app.router.lifespan_context = lifespan
app.mount("/mcp", mcp_http_app)

import os, time, json, sqlite3
from typing import Any, Optional
import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from dotenv import load_dotenv

load_dotenv()
API_KEY=os.getenv("API_FOOTBALL_KEY","").strip()
GATEWAY_TOKEN=os.getenv("GATEWAY_TOKEN","").strip()
DAILY_LIMIT=int(os.getenv("API_DAILY_LIMIT","90"))
BASE_URL=os.getenv("API_FOOTBALL_BASE_URL","https://v3.football.api-sports.io").rstrip("/")
CACHE_TTL=int(os.getenv("CACHE_TTL_SECONDS","900"))
DB_PATH=os.getenv("DB_PATH","data/gateway.db")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

app=FastAPI(title="Bankroll Engine V2.2 API-Football Gateway",version="1.0.0")

def db():
    c=sqlite3.connect(DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS cache(cache_key TEXT PRIMARY KEY,created INTEGER,payload TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS usage(day TEXT PRIMARY KEY,requests INTEGER)")
    c.commit(); return c

def day(): return time.strftime("%Y-%m-%d",time.gmtime())
def usage():
    c=db(); r=c.execute("SELECT requests FROM usage WHERE day=?",(day(),)).fetchone(); c.close()
    return r[0] if r else 0
def auth(token):
    if not GATEWAY_TOKEN: raise HTTPException(500,"GATEWAY_TOKEN is not configured")
    if token != GATEWAY_TOKEN: raise HTTPException(401,"Invalid gateway token")

async def get_api(path,params):
    if not API_KEY: raise HTTPException(500,"API_FOOTBALL_KEY is not configured")
    params={k:v for k,v in params.items() if v not in (None,"")}
    key=path+"?"+json.dumps(params,sort_keys=True)
    c=db(); r=c.execute("SELECT created,payload FROM cache WHERE cache_key=?",(key,)).fetchone(); c.close()
    if r and time.time()-r[0] < CACHE_TTL:
        return json.loads(r[1]),True
    if usage() >= DAILY_LIMIT: raise HTTPException(429,f"API daily safety limit reached: {DAILY_LIMIT}")
    async with httpx.AsyncClient(timeout=25) as client:
        resp=await client.get(BASE_URL+path,params=params,headers={"x-apisports-key":API_KEY})
    if resp.status_code>=400: raise HTTPException(resp.status_code,resp.text[:500])
    data=resp.json()
    c=db()
    c.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)",(key,int(time.time()),json.dumps(data)))
    c.execute("""INSERT INTO usage(day,requests) VALUES(?,1)
                 ON CONFLICT(day) DO UPDATE SET requests=requests+1""",(day(),))
    c.commit(); c.close()
    return data,False

def out(data,cached):
    return {"cached":cached,"usage_today":usage(),"daily_safety_limit":DAILY_LIMIT,"data":data}

@app.get("/health")
async def health():
    return {"ok":True,"api_key_configured":bool(API_KEY),"gateway_auth_configured":bool(GATEWAY_TOKEN),
            "usage_today":usage(),"daily_safety_limit":DAILY_LIMIT}

@app.get("/api/status")
async def status(x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token)
    return {"api_football":bool(API_KEY),"usage_today":usage(),"daily_safety_limit":DAILY_LIMIT}

@app.get("/fixtures")
async def fixtures(date:Optional[str]=None,league:Optional[int]=None,season:Optional[int]=None,
                   team:Optional[int]=None,fixture:Optional[int]=None,status:Optional[str]=None,
                   x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token)
    d,c=await get_api("/fixtures",{"date":date,"league":league,"season":season,"team":team,"id":fixture,"status":status})
    return out(d,c)

@app.get("/fixtures/{fixture_id}/statistics")
async def statistics(fixture_id:int,x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token); d,c=await get_api("/fixtures/statistics",{"fixture":fixture_id}); return out(d,c)

@app.get("/fixtures/{fixture_id}/lineups")
async def lineups(fixture_id:int,x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token); d,c=await get_api("/fixtures/lineups",{"fixture":fixture_id}); return out(d,c)

@app.get("/fixtures/{fixture_id}/injuries")
async def injuries(fixture_id:int,x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token); d,c=await get_api("/injuries",{"fixture":fixture_id}); return out(d,c)

@app.get("/fixtures/{fixture_id}/predictions")
async def predictions(fixture_id:int,x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token); d,c=await get_api("/predictions",{"fixture":fixture_id}); return out(d,c)

@app.get("/fixtures/{fixture_id}/odds")
async def odds(fixture_id:int,x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token); d,c=await get_api("/odds",{"fixture":fixture_id}); return out(d,c)

@app.get("/h2h")
async def h2h(h2h:str,last:int=10,x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token); d,c=await get_api("/fixtures/headtohead",{"h2h":h2h,"last":last}); return out(d,c)

@app.get("/teams/{team_id}/statistics")
async def team_stats(team_id:int,league:int,season:int,x_gateway_token:Optional[str]=Header(None)):
    auth(x_gateway_token); d,c=await get_api("/teams/statistics",{"team":team_id,"league":league,"season":season}); return out(d,c)

# Bankroll Engine V2.2 — API-Football Gateway

Готовый API-шлюз для API-Football. Ключ API-Football хранится только на сервере.
Наружу выдаются данные через защищённые endpoints.

## Endpoints
- GET /health
- GET /api/status
- GET /fixtures
- GET /fixtures/{fixture_id}/statistics
- GET /fixtures/{fixture_id}/lineups
- GET /fixtures/{fixture_id}/injuries
- GET /fixtures/{fixture_id}/predictions
- GET /fixtures/{fixture_id}/odds
- GET /h2h?h2h=HOME-AWAY&last=10
- GET /teams/{team_id}/statistics?league=...&season=...

Защищённые endpoints требуют header:
X-Gateway-Token: <GATEWAY_TOKEN>

## Локально
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

Swagger: http://127.0.0.1:8000/docs

## Render
Build: pip install -r requirements.txt
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT

В Render добавь API_FOOTBALL_KEY и GATEWAY_TOKEN как Environment Variables.
Не коммить .env.

ACTIVE_CORE=v22 — текущий production core. Позже шлюз не меняется при замене ядра на v23.


## ChatGPT bridge

This version adds a separate read-only bridge for ChatGPT/web access.

Set a strong `CHATGPT_BRIDGE_TOKEN` in Render. Do not reuse `API_FOOTBALL_KEY` or `GATEWAY_TOKEN`.

Bridge examples:
- `/chat/<CHATGPT_BRIDGE_TOKEN>/fixtures?date=YYYY-MM-DD`
- `/chat/<CHATGPT_BRIDGE_TOKEN>/fixtures/<fixture_id>/statistics`
- `/chat/<CHATGPT_BRIDGE_TOKEN>/fixtures/<fixture_id>/lineups`
- `/chat/<CHATGPT_BRIDGE_TOKEN>/fixtures/<fixture_id>/injuries`
- `/chat/<CHATGPT_BRIDGE_TOKEN>/fixtures/<fixture_id>/predictions`
- `/chat/<CHATGPT_BRIDGE_TOKEN>/fixtures/<fixture_id>/odds`
- `/chat/<CHATGPT_BRIDGE_TOKEN>/h2h?h2h=home_id-home_id&last=10`
- `/chat/<CHATGPT_BRIDGE_TOKEN>/teams/<team_id>/statistics?league=<league_id>&season=<season>`

Security model:
- API-Football key remains server-side.
- Existing `GATEWAY_TOKEN` remains separate.
- ChatGPT bridge token only authorizes the read-only bridge routes.
- The bridge never returns secrets.
- Rotate the bridge token if it is exposed.

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

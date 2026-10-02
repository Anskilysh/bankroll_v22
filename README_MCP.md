# Bankroll Engine V2.2 — API-Football ChatGPT MCP Connector

This update adds a read-only MCP endpoint to the existing Render gateway.

## MCP endpoint

`https://bankroll-v22.onrender.com/mcp`

Authentication:

`Authorization: Bearer <CHATGPT_MCP_TOKEN>`

If `CHATGPT_MCP_TOKEN` is not set, the existing `CHATGPT_BRIDGE_TOKEN` is used as a fallback.

## Tools

- `get_fixtures`
- `get_fixture_statistics`
- `get_lineups`
- `get_injuries`
- `get_fixture_prediction`
- `get_fixture_odds`
- `get_h2h`
- `get_team_statistics`
- `get_gateway_usage`

All tools are read-only.

## API-Football semantics

- `results=0` is treated as NO_DATA, not proof of absence.
- API plan restrictions are returned by API-Football and are not converted into fabricated data.
- The 90 requests/day safety limit remains active.
- Existing SQLite cache remains active.
- Existing gateway endpoints remain available.

## Render

After replacing the files, redeploy the service.

Set these Render environment variables:

- `API_FOOTBALL_KEY`
- `GATEWAY_TOKEN`
- `CHATGPT_BRIDGE_TOKEN`
- `CHATGPT_MCP_TOKEN`

Do not commit the actual secret values.

## ChatGPT

After Render is live, add the remote MCP server using:

`https://bankroll-v22.onrender.com/mcp`

and authenticate with the Bearer token stored in `CHATGPT_MCP_TOKEN`.

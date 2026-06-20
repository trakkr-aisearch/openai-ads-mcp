# openai-ads-mcp for Node

Node runtime for `openai-ads-mcp`, a typed MCP server for OpenAI's Advertiser API.

It exposes the same tools, arguments, defaults, readonly mode, and budget guard as the Python package.

## Quickstart

```bash
export OPENAI_ADS_API_KEY="..."
export OPENAI_ADS_MCP_READONLY=1
npx -y openai-ads-mcp
```

Readonly mode hides every write tool from `tools/list`. Unset `OPENAI_ADS_MCP_READONLY` only after you have confirmed the account and reviewed existing campaigns.

## Local Development

```bash
npm install
npm run build
npm test
OPENAI_ADS_MCP_READONLY=1 node dist/index.js
```

## Streamable HTTP

For hosted or team deployments, start the Node runtime with Streamable HTTP:

```bash
export OPENAI_ADS_MCP_HTTP_TOKEN="choose_a_long_random_token"
npx -y openai-ads-mcp --http
```

The MCP endpoint is `/mcp`, the health endpoint is `/healthz`, and remote mode is read-only by default. Set `OPENAI_ADS_MCP_HTTP_ALLOW_WRITES=1` only when write tools should be visible over HTTP. Clients can pass `X-OpenAI-Ads-API-Key` per request, or the server can use a server-side `OPENAI_ADS_API_KEY`.

## Environment

| Variable | Purpose |
| --- | --- |
| `OPENAI_ADS_API_KEY` | Required bearer key for `https://api.ads.openai.com/v1`. |
| `OPENAI_ADS_API_BASE_URL` | Optional HTTPS override for tests or proxies. |
| `OPENAI_ADS_MCP_READONLY` | Set to `1` or `true` to register read tools only. |
| `OPENAI_ADS_BUDGET_CEILING_USD` | Optional budget guard. Default `100`. |
| `OPENAI_ADS_MCP_HTTP_TOKEN` | Optional bearer token for hosted HTTP mode. |
| `OPENAI_ADS_MCP_HTTP_ALLOW_WRITES` | Set to `1` to expose write tools in HTTP mode. |

Full docs live in the repository root README.

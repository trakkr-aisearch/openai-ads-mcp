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

## Environment

| Variable | Purpose |
| --- | --- |
| `OPENAI_ADS_API_KEY` | Required bearer key for `https://api.ads.openai.com/v1`. |
| `OPENAI_ADS_API_BASE_URL` | Optional HTTPS override for tests or proxies. |
| `OPENAI_ADS_MCP_READONLY` | Set to `1` or `true` to register read tools only. |
| `OPENAI_ADS_BUDGET_CEILING_USD` | Optional budget guard. Default `100`. |

Full docs live in the repository root README.

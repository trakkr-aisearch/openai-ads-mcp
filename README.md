# openai-ads-mcp

Trakkr tracks the full AI-visibility funnel, organic and paid. This is the open-source paid-side companion.

`openai-ads-mcp` is a typed Model Context Protocol server for OpenAI's Advertiser API. It lets Claude, Cursor, Codex, VS Code, and other MCP clients inspect Ads accounts, read performance insights, build paused campaigns, upload creatives, manage audiences, and send conversion events.

It ships in two runtimes with the same tool names, arguments, defaults, safety model, and vendored OpenAPI reference:

| Runtime | Best install | Package path |
| --- | --- | --- |
| Python | `uvx openai-ads-mcp` | `python/` |
| Node | `npx -y openai-ads-mcp` | `typescript/` |

The goal is simple: make OpenAI Ads workable from an AI assistant without making spend easy to trigger by accident.

## Install

Python with `uvx`:

```bash
uvx openai-ads-mcp
```

Python with pip:

```bash
python -m pip install openai-ads-mcp
openai-ads-mcp
```

Node with `npx`:

```bash
npx -y openai-ads-mcp
```

Node with npm:

```bash
npm install -g openai-ads-mcp
openai-ads-mcp
```

For local development from this monorepo:

```bash
cd services/openai-ads-mcp/python
python -m pip install -e .
python -m openai_ads_mcp

cd ../typescript
npm install
npm run build
node dist/index.js
```

## Configuration

Create an Ads API key in OpenAI Ads Manager, then pass it as an environment variable.

```bash
export OPENAI_ADS_API_KEY="..."
```

Recommended first connection:

```bash
export OPENAI_ADS_MCP_READONLY=1
uvx openai-ads-mcp
```

Or with Node:

```bash
export OPENAI_ADS_MCP_READONLY=1
npx -y openai-ads-mcp
```

Readonly mode hides every write tool. They are absent from `tools/list` and cannot be called. Once you have confirmed the account and inspected data, unset `OPENAI_ADS_MCP_READONLY` to enable writes.

Optional environment variables:

| Variable | Purpose |
| --- | --- |
| `OPENAI_ADS_API_KEY` | Required bearer key for `https://api.ads.openai.com/v1`. |
| `OPENAI_ADS_API_BASE_URL` | Optional HTTPS override for tests or proxies. |
| `OPENAI_ADS_MCP_READONLY` | Set to `1` or `true` to register read tools only. |
| `OPENAI_ADS_BUDGET_CEILING_USD` | Optional budget guard. Default `100`. |

## Discovery Metadata

This repo includes `server.json` for the official MCP Registry and downstream MCP directories. The canonical registry name is:

```text
io.github.trakkr-aisearch/openai-ads-mcp
```

The Node package includes the matching `mcpName`, and the Python package README includes the matching `mcp-name` marker for PyPI ownership verification.

## MCP client examples

### Claude Code, Python runtime

```bash
claude mcp add openai-ads \
  -e OPENAI_ADS_API_KEY=your_ads_key_here \
  -e OPENAI_ADS_MCP_READONLY=1 \
  -- uvx openai-ads-mcp
```

### Claude Code, Node runtime

```bash
claude mcp add openai-ads \
  -e OPENAI_ADS_API_KEY=your_ads_key_here \
  -e OPENAI_ADS_MCP_READONLY=1 \
  -- npx -y openai-ads-mcp
```

### Cursor or Claude Desktop

```json
{
  "mcpServers": {
    "openai-ads": {
      "command": "uvx",
      "args": ["openai-ads-mcp"],
      "env": {
        "OPENAI_ADS_API_KEY": "your_ads_key_here",
        "OPENAI_ADS_MCP_READONLY": "1"
      }
    }
  }
}
```

Use `"command": "npx"` and `"args": ["-y", "openai-ads-mcp"]` for the Node runtime.

### Codex CLI

```toml
[mcp_servers.openai_ads]
command = "uvx"
args = ["openai-ads-mcp"]
env = { OPENAI_ADS_API_KEY = "your_ads_key_here", OPENAI_ADS_MCP_READONLY = "1" }
```

## Streamable HTTP

The Node runtime can also serve MCP over Streamable HTTP for hosted or team deployments:

```bash
export OPENAI_ADS_MCP_HTTP_TOKEN="choose_a_long_random_token"
npx -y openai-ads-mcp --http
```

Defaults:

- URL: `http://127.0.0.1:8080/mcp` locally, or `https://your-host/mcp` behind a proxy.
- Health check: `GET /healthz`.
- Remote mode forces `OPENAI_ADS_MCP_READONLY=1` unless `OPENAI_ADS_MCP_HTTP_ALLOW_WRITES=1` is set.
- `OPENAI_ADS_MCP_HTTP_TOKEN` protects the MCP endpoint with `Authorization: Bearer <token>`.
- Clients may send `X-OpenAI-Ads-API-Key` per request, or the server can use a server-side `OPENAI_ADS_API_KEY`.

Useful hosted env vars:

| Variable | Purpose |
| --- | --- |
| `PORT` or `OPENAI_ADS_MCP_HTTP_PORT` | HTTP port. Default `8080`. |
| `OPENAI_ADS_MCP_HTTP_PATH` | MCP path. Default `/mcp`. |
| `OPENAI_ADS_MCP_HEALTH_PATH` | Health path. Default `/healthz`. |
| `OPENAI_ADS_MCP_HTTP_TOKEN` | Optional bearer token required by hosted clients. |
| `OPENAI_ADS_MCP_HTTP_ALLOW_WRITES` | Set to `1` only when you want write tools exposed over HTTP. |
| `OPENAI_ADS_MCP_HTTP_CORS_ORIGIN` | Optional CORS origin. Default `*`. |

For public hosted endpoints, keep writes disabled by default and inject Ads API keys server-side through your own OAuth or credential vault. Do not put a shared Ads API key in browser-visible config.

## Tool Surface

The Python and Node runtimes expose the same 27 tools.

| Group | Tools |
| --- | --- |
| Account | `get_account` |
| Campaigns | `list_campaigns`, `get_campaign`, `create_campaign`, `update_campaign`, `set_campaign_state` |
| AdGroups | `list_ad_groups`, `get_ad_group`, `create_ad_group`, `update_ad_group`, `set_ad_group_state` |
| Ads | `list_ads`, `get_ad`, `upload_creative`, `create_ad`, `update_ad`, `set_ad_state` |
| Insights | `get_insights` |
| Audiences | `list_audiences`, `get_audience`, `search_geo`, `manage_audience` |
| Conversions | `manage_conversions`, `send_conversions` |
| Helpers | `build_campaign`, `draft_context_hints`, `bulk_ab_test_hints` |

### High-use tools

| Tool | What it does |
| --- | --- |
| `get_account` | Gets the ad account and confirms the API key works. |
| `get_insights` | Reads account, campaign, ad group, or ad insights with fields, filters, sort, segments, and cursor pagination. |
| `create_campaign` | Creates a paused campaign with a guarded lifetime budget. |
| `upload_creative` | Uploads an image URL or local image file and returns `file_id`. |
| `create_ad` | Creates a paused ad. `chat_card` requires `target_url` and `file_id`. |
| `build_campaign` | Creates one paused campaign, one paused ad group, and paused ads in a guarded workflow. |
| `draft_context_hints` | Deterministically drafts API-shaped `context_hints` with no hidden LLM call. |
| `send_conversions` | Sends conversion events to `https://bzr.openai.com/v1/events?pid=...` after local validation. |

## Safety Model

This server can affect real ad spend, so the defaults are deliberately cautious.

1. Create tools default to paused. `build_campaign` creates every object paused.
2. Activations are separate tools: `set_campaign_state`, `set_ad_group_state`, and `set_ad_state`.
3. Budget-setting paths enforce `OPENAI_ADS_BUDGET_CEILING_USD`, default `100`.
4. To exceed the ceiling, pass `confirm_budget=True`.
5. `OPENAI_ADS_MCP_READONLY=1` hides every write tool entirely.
6. Conversion ingest validates at most 1000 events per call, timestamps no older than 7 days, and timestamps no more than 10 minutes in the future.
7. The server never logs API keys or conversion user data.

MCP annotations are set on every tool. Read tools use `readOnlyHint`. Write tools use `readOnlyHint=false`. Activation and budget-changing tools are marked destructive and open-world so hosts can prompt before running them.

## Worked Example

First, connect safely:

```bash
export OPENAI_ADS_API_KEY="..."
export OPENAI_ADS_MCP_READONLY=1
uvx openai-ads-mcp
```

Ask your assistant:

```text
Call get_account and list_campaigns. Confirm the Ads key works and show me what already exists.
```

Then restart without readonly mode and build a paused campaign:

```text
Use draft_context_hints for "AI visibility monitoring software" aimed at growth teams with comparison intent.

Then call build_campaign with:
- name: "AI visibility category test"
- budget_usd: 50
- ad_group: name "Growth teams", billing_event "click", max_bid_usd 1.25, context_hints from the draft
- ads: two chat_card variants using my uploaded file_id

Do not activate anything.
```

Review the returned campaign, ad group, ads, budget, targeting, and review status. When you are ready to go live, activate each layer explicitly:

```text
Call set_campaign_state with state="activate".
Call set_ad_group_state with state="activate".
Call set_ad_state for the approved ad with state="activate".
```

## The Organic Half

Paid placements answer: where did you buy attention?

Trakkr answers: where does your brand show up organically across ChatGPT, Perplexity, Gemini, Claude, Google AI Overviews, Reddit, citations, rankings, competitors, sentiment, prompts, reports, and actions?

Track the organic side at [trakkr.ai](https://trakkr.ai). Use the Trakkr generator at [trakkr.ai/create](https://trakkr.ai/create) when you want to turn AI-search gaps into content briefs.

This MCP also exposes one optional resource:

```text
openai-ads://trakkr-visibility
```

It returns a short paste-ready briefing that connects buying ChatGPT ad placements with tracking organic ChatGPT visibility. It is never injected into tool results.

## Development

Python:

```bash
cd services/openai-ads-mcp/python
python -m pytest -q
python -c "import openai_ads_mcp; print('ok')"
```

Node:

```bash
cd services/openai-ads-mcp/typescript
npm install
npm run build
npm test
OPENAI_ADS_MCP_READONLY=1 node dist/index.js
```

OpenAPI drift check:

```bash
cd services/openai-ads-mcp/typescript
npm run check:openapi
```

## Release Status

This package is beta. Before the first public release, confirm that the PyPI and npm package names `openai-ads-mcp` are available. See `RELEASING.md`.

## License

MIT, copyright Trakkr.

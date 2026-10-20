# openai-ads-mcp

Trakkr tracks the full AI-visibility funnel, organic and paid. This is the open-source paid-side companion.

`openai-ads-mcp` is a typed Model Context Protocol server for OpenAI Ads, ChatGPT Ads, and OpenAI's Advertiser API. It lets Claude, Cursor, Codex, VS Code, and other MCP clients inspect Ads accounts, read performance insights, build paused campaigns, upload creatives, manage audiences, and send conversion events.

People often search for this as a ChatGPT Ads MCP because the ads appear in ChatGPT. The package keeps the OpenAI Ads MCP name because ChatGPT Ads are managed through OpenAI Ads, Ads Manager, and the OpenAI Advertiser API.

Current public release: `0.1.7`.

It ships in two runtimes with the same tool names, arguments, defaults, safety model, and vendored OpenAPI reference:

| Runtime | Best install | Package path |
| --- | --- | --- |
| Python | `uvx openai-ads-mcp` | `python/` |
| Node | `npx -y openai-ads-mcp` | `typescript/` |

The goal is simple: make OpenAI Ads workable from an AI assistant without making spend easy to trigger by accident.

## Install

Python with `uvx`:

```bash
export OPENAI_ADS_API_KEY="..."
export OPENAI_ADS_MCP_READONLY=1
uvx openai-ads-mcp
```

Python with pip:

```bash
python -m pip install openai-ads-mcp
export OPENAI_ADS_API_KEY="..."
export OPENAI_ADS_MCP_READONLY=1
openai-ads-mcp
```

Node with `npx`:

```bash
export OPENAI_ADS_API_KEY="..."
export OPENAI_ADS_MCP_READONLY=1
npx -y openai-ads-mcp
```

Node with npm:

```bash
npm install -g openai-ads-mcp
export OPENAI_ADS_API_KEY="..."
export OPENAI_ADS_MCP_READONLY=1
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
| `OPENAI_ADS_MCP_TOOLS` | Comma-separated write tool names. When set, only those write tools are registered (read tools always are). `OPENAI_ADS_MCP_READONLY` still wins. |
| `OPENAI_ADS_BUDGET_CEILING` | Optional total-spend guard, in the ad account's currency (major units). Default `100`. Falls back to the legacy `OPENAI_ADS_BUDGET_CEILING_USD` (logs a deprecation warning). `off` (any case) removes the ceiling and the `end_time` rule; the amount must still be finite and at least `1`. |
| `OPENAI_ADS_BID_CEILING` | Optional bid guard, in the ad account's currency (major units). Default `10`. A higher `max_bid` needs `confirm_bid=True`. `off` (any case) removes the ceiling. |
| `OPENAI_ADS_ALLOW_LOCAL_FILES` | Set to `1` to let `upload_creative` and `manage_audience` read `file_path` from the server's disk. Off by default; send `file_content_base64` (or `image_url` / `file_id`) instead. |
| `OPENAI_ADS_ENABLE_FEED_WRITES` | Set to `1` to list `update_product_feed_products`. Off by default because the feed price unit is unverified. |

## Discovery Metadata

This repo includes `server.json` for the official MCP Registry and downstream MCP directories. The canonical registry name is:

```text
io.github.trakkr-aisearch/openai-ads-mcp
```

The Node package includes the matching `mcpName`, and the Python package README includes the matching `mcp-name` marker for PyPI ownership verification.

The registry metadata also advertises the hosted read-only Streamable HTTP endpoint:

```text
https://openai-ads-mcp.trakkr.ai/mcp
```

That hosted endpoint is for discovery and read-only usage. It does not store or use a Trakkr-owned OpenAI Ads API key.
The hosted endpoint allows anonymous initialize and `tools/list`; Ads API tool calls require the caller to send `X-OpenAI-Ads-API-Key`.

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

### MCP Registry

Registry-compatible clients should discover this server by name:

```text
io.github.trakkr-aisearch/openai-ads-mcp
```

The registry metadata lists npm, PyPI, and the hosted Streamable HTTP endpoint. The hosted endpoint does not require an API key for discovery, but it does require `X-OpenAI-Ads-API-Key` for Ads API tool calls.

### Docker

The repository includes production Dockerfiles for hosted Streamable HTTP deployments:

```bash
docker build -t openai-ads-mcp .
docker run --rm -p 8080:8080 \
  -e OPENAI_ADS_MCP_HOSTED_PUBLIC=1 \
  -e OPENAI_ADS_MCP_TELEMETRY_SALT="local-test-salt" \
  openai-ads-mcp
```

The narrower `typescript/Dockerfile` is used by the Cloud Run deploy script. For local stdio use, prefer `uvx openai-ads-mcp` or `npx -y openai-ads-mcp`.

## Streamable HTTP

The Node runtime can also serve MCP over Streamable HTTP for hosted or team deployments:

```bash
export OPENAI_ADS_MCP_HTTP_TOKEN="choose_a_long_random_token"
export OPENAI_ADS_MCP_READONLY=1
npx -y openai-ads-mcp --http
```

Defaults:

- URL: `http://127.0.0.1:8080/mcp` locally, or `https://your-host/mcp` behind a proxy.
- Health checks: `GET /healthz`, `GET /health`, and `GET /ready`.
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

For public hosted endpoints, keep writes disabled and require users to bring their own Ads API key per request. Do not put a shared Ads API key in browser-visible config.

### Public hosted mode

For a public discovery endpoint, use:

```bash
export OPENAI_ADS_MCP_HOSTED_PUBLIC=1
export OPENAI_ADS_MCP_TELEMETRY_SALT="long_random_value"
npx -y openai-ads-mcp --http
```

Hosted public mode:

- forces readonly mode
- refuses to start if `OPENAI_ADS_MCP_HTTP_ALLOW_WRITES=1`
- refuses to start if `OPENAI_ADS_API_KEY` is present
- rejects `X-OpenAI-Ads-API-Base-Url`
- allows anonymous initialize and `tools/list`
- requires `X-OpenAI-Ads-API-Key` for Ads API tool calls
- rate-limits discovery and tool calls
- logs only redacted summaries, hashes, counts, status, latency, and client metadata

The production runbook is in `HOSTED_DEPLOY.md`.

## Tool Surface

The upstream manifest lists 27 tools. This fork's Python runtime adds `get_conversions`, `set_ad_account_state`, `update_ad_account_brand`, the daily spend limit tools (`get_spend_limits`, `set_daily_spend_limit`, `remove_daily_spend_limit`), and `update_product_feed_products` (34 listed by default, 35 with `OPENAI_ADS_ENABLE_FEED_WRITES=1`; 15 in readonly mode).

| Group | Tools |
| --- | --- |
| Account | `get_account` |
| Campaigns | `list_campaigns`, `get_campaign`, `create_campaign`, `update_campaign`, `set_campaign_state` |
| AdGroups | `list_ad_groups`, `get_ad_group`, `create_ad_group`, `update_ad_group`, `set_ad_group_state` |
| Ads | `list_ads`, `get_ad`, `upload_creative`, `create_ad`, `update_ad`, `set_ad_state` |
| Insights | `get_insights` |
| Audiences | `list_audiences`, `get_audience`, `search_geo`, `manage_audience` |
| Conversions | `get_conversions` (read), `manage_conversions`, `send_conversions` |
| Helpers | `build_campaign`, `draft_context_hints`, `bulk_ab_test_hints` |

### High-use tools

| Tool | What it does |
| --- | --- |
| `get_account` | Gets the ad account and confirms the API key works. |
| `get_insights` | Reads account, campaign, ad group, or ad insights with fields, filters, sort, segments, and cursor pagination. |
| `create_campaign` | Creates a paused campaign with a guarded lifetime budget, including conversion-optimized campaigns with one event setting. |
| `upload_creative` | Uploads an image URL or local image file and returns `file_id`. |
| `create_ad` | Creates a paused ad. `chat_card` requires `target_url` and `file_id`. |
| `build_campaign` | Creates one paused campaign, one paused ad group, and paused ads in a guarded workflow. |
| `draft_context_hints` | Deterministically drafts API-shaped `context_hints` with no hidden LLM call. |
| `send_conversions` | Sends conversion events to `https://bzr.openai.com/v1/events?pid=...` after local validation, with optional `validate_only`. Supports `obref` and mobile app lifecycle events. |

`get_insights` accepts the current tagged time-range shape, for example:

```json
{"type":"unix_range","start":1764547200,"end":1765152000}
```

The older nested shape is normalized for backward compatibility.

For conversion optimization, pass `bidding_type="conversions"` and exactly one
`conversion_event_setting_ids` value to `create_campaign`. The campaign cannot
use product-feed mode, and child ad groups must bill by click. `build_campaign`
offers the same path through its singular `conversion_event_setting_id` helper
argument. The bid is a CPA input even though OpenAI bills the child ad group per
click.

OpenAI's Bulk API remains a limited preview and is not exposed as a general MCP
tool. Product-feed campaign objects are supported, but feed connection and
catalog upload still happen in Ads Manager or through OpenAI's supported SFTP
flow.

## Safety Model

This server can affect real ad spend, so the defaults are deliberately cautious.

1. Create tools default to paused. `build_campaign` creates every object paused.
2. Activations are separate tools: `set_campaign_state`, `set_ad_group_state`, and `set_ad_state`.
3. Budgets (`lifetime_budget`, `daily_budget`) are amounts in the ad account's currency, major units (`500` = ₹500 on an INR account, $500 on a USD account; `get_account` shows the currency). Set one or the other, not both. `OPENAI_ADS_BUDGET_CEILING` (default `100` in that currency) caps total spend: a `lifetime_budget` above it, or a `daily_budget` with no `end_time` or whose daily amount × days until `end_time` exceeds it, needs `confirm_budget=True`. Ad group bids (`max_bid`) use the same currency and units; above `OPENAI_ADS_BID_CEILING` (default `10`) they need `confirm_bid=True`.
4. Bidding edits read the ad group first and resend its current strategy, bid and audience multipliers for whatever you leave out, so changing one never resets the others. Creates send an `Idempotency-Key` (generated when you pass none). Ids that would change the request path (`..`, `?`, `#`) are refused before anything is sent.
5. `OPENAI_ADS_MCP_READONLY=1` hides every write tool entirely.
6. Conversion ingest validates at most 1000 events per call, timestamps no older than 7 days, and timestamps no more than 10 minutes in the future.
7. Use `validate_only=true` to validate a conversion batch without ingesting it.
8. The server never logs API keys or conversion user data.

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
- lifetime_budget: 50 (in the ad account's currency)
- ad_group: name "Growth teams", billing_event "click", max_bid 1.25, context_hints from the draft
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
npm run check:docs
```

The scheduled workflow runs both checks weekly. The OpenAPI comparison catches
schema drift. The guide check covers current behavior documented outside the
downloadable schema, including tagged insight ranges, `obref`, mobile app
events, conversion optimization, advertiser readiness, required chat-card
images, and the limited-preview Bulk API.

## Release Status

`0.1.7` is the current public beta release for npm, PyPI, the hosted endpoint, and the live MCP Registry entry. Registry metadata versions are immutable, so registry-only corrections in this repo should ship with the next package release version. Release work is synced to the dedicated public repository before publishing. See `RELEASING.md`.

## License

MIT, copyright Trakkr.

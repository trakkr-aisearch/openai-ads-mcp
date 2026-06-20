import assert from "node:assert/strict";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test, { afterEach, beforeEach } from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

import { OpenAIAdsAPIError, OpenAIAdsClient } from "../dist/client.js";
import {
  allToolDefinitions,
  registeredToolDefinitions,
  registeredToolMetadata,
} from "../dist/index.js";
import {
  handleApiError,
  resetClientFactoryForTests,
  runWithRequestAuth,
  setClientFactoryForTests,
} from "../dist/core.js";
import { startHttpServer } from "../dist/http.js";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const manifest = JSON.parse(await readFile(new URL("../../mcpToolManifest.json", import.meta.url), "utf8"));
const expectedNames = manifest.tools.map((tool) => tool.name);

const expectedArgMap = new Map(Object.entries({
  build_campaign: ["name", "budget_usd", "ad_group", "ads", "confirm_budget"],
  bulk_ab_test_hints: ["ad_group_id", "variants"],
  create_ad: ["ad_group_id", "name", "creative_type", "title", "body", "target_url", "file_id", "price", "status"],
  create_ad_group: ["campaign_id", "name", "billing_event", "max_bid_usd", "status", "context_hints"],
  create_campaign: ["name", "budget_usd", "status", "description", "start_time", "end_time", "mode", "locations", "confirm_budget"],
  draft_context_hints: ["product", "audience", "intent", "keywords"],
  get_account: [],
  get_ad: ["ad_id"],
  get_ad_group: ["ad_group_id"],
  get_audience: ["audience_id"],
  get_campaign: ["campaign_id"],
  get_insights: ["scope", "entity_id", "time_granularity", "time_range", "segments", "fields", "filters", "sort", "limit", "after", "before", "response_format"],
  list_ad_groups: ["campaign_id", "limit", "after", "before", "order"],
  list_ads: ["ad_group_id", "limit", "after", "before", "order"],
  list_audiences: ["limit", "after", "before", "order"],
  list_campaigns: ["limit", "after", "before", "order"],
  manage_audience: ["action", "name", "description", "members", "audience_id", "file_id", "identifier_type", "filename", "mimetype", "file_size"],
  manage_conversions: ["action", "name", "client_type", "event_type", "custom_event_name", "attribution_window_days", "source_ids", "aggregation_level", "time_ranges", "entity_ids", "limit", "after", "before", "order"],
  search_geo: ["query"],
  send_conversions: ["pixel_id", "events"],
  set_ad_group_state: ["ad_group_id", "state"],
  set_ad_state: ["ad_id", "state"],
  set_campaign_state: ["campaign_id", "state"],
  update_ad: ["ad_id", "name", "creative_type", "title", "body", "target_url", "file_id", "price", "status"],
  update_ad_group: ["ad_group_id", "name", "billing_event", "max_bid_usd", "status", "context_hints"],
  update_campaign: ["campaign_id", "name", "budget_usd", "status", "description", "start_time", "end_time", "mode", "locations", "confirm_budget"],
  upload_creative: ["image_url", "file_path"],
}));

const expectedWriteTools = new Set([
  "create_campaign",
  "update_campaign",
  "set_campaign_state",
  "create_ad_group",
  "update_ad_group",
  "set_ad_group_state",
  "upload_creative",
  "create_ad",
  "update_ad",
  "set_ad_state",
  "manage_audience",
  "manage_conversions",
  "send_conversions",
  "build_campaign",
  "bulk_ab_test_hints",
]);

const expectedDestructiveTools = new Set([
  "create_campaign",
  "update_campaign",
  "set_campaign_state",
  "set_ad_group_state",
  "set_ad_state",
  "manage_audience",
  "build_campaign",
]);

const expectedOpenWorldTools = new Set([
  "create_campaign",
  "update_campaign",
  "set_campaign_state",
  "set_ad_group_state",
  "set_ad_state",
  "send_conversions",
  "build_campaign",
]);

const usedOpenAIAdsPaths = new Set([
  "/ad_account",
  "/ad_account/insights",
  "/campaigns",
  "/campaigns/{campaign_id}",
  "/campaigns/{campaign_id}/activate",
  "/campaigns/{campaign_id}/pause",
  "/campaigns/{campaign_id}/archive",
  "/campaigns/{campaign_id}/insights",
  "/ad_groups",
  "/ad_groups/{ad_group_id}",
  "/ad_groups/{ad_group_id}/activate",
  "/ad_groups/{ad_group_id}/pause",
  "/ad_groups/{ad_group_id}/archive",
  "/ad_groups/{ad_group_id}/insights",
  "/ads",
  "/ads/{ad_id}",
  "/ads/{ad_id}/activate",
  "/ads/{ad_id}/pause",
  "/ads/{ad_id}/archive",
  "/ads/{ad_id}/insights",
  "/upload",
  "/custom_audiences",
  "/custom_audiences/{custom_audience_id}",
  "/custom_audiences/upload",
  "/custom_audiences/{custom_audience_id}/archive",
  "/conversions/pixels",
  "/conversions/api_keys",
  "/conversions/event_settings",
  "/conversions/insights",
  "/geo_lookup/search",
]);

let mockClient;
let originalFetch;

function makeMockClient(options = {}) {
  const calls = [];
  const postResponses = [...(options.postResponses ?? [])];
  return {
    calls,
    async get(path, params) {
      calls.push({ method: "get", path, params });
      return { ok: true, data: [] };
    },
    async post(path, body) {
      calls.push({ method: "post", path, body });
      const next = postResponses.length ? postResponses.shift() : { ok: true, id: "created" };
      if (next instanceof Error) throw next;
      return next;
    },
    async uploadFile(path, filePath) {
      calls.push({ method: "uploadFile", path, filePath });
      return { file_id: "file_123" };
    },
    async postConversions(pixelId, events) {
      calls.push({ method: "postConversions", pixelId, events });
      return { ok: true, received: events.length };
    },
  };
}

function tool(name) {
  const found = allToolDefinitions.find((definition) => definition.name === name);
  assert.ok(found, `Missing tool ${name}`);
  return found;
}

async function callTool(name, args = {}) {
  return JSON.parse(await tool(name).handler(args));
}

beforeEach(() => {
  mockClient = makeMockClient();
  setClientFactoryForTests(() => mockClient);
  originalFetch = globalThis.fetch;
  delete process.env.OPENAI_ADS_MCP_READONLY;
  delete process.env.OPENAI_ADS_BUDGET_CEILING_USD;
  delete process.env.OPENAI_ADS_MCP_HTTP_ALLOW_WRITES;
  delete process.env.OPENAI_ADS_MCP_HTTP_TOKEN;
});

afterEach(() => {
  resetClientFactoryForTests();
  globalThis.fetch = originalFetch;
  delete process.env.OPENAI_ADS_MCP_READONLY;
  delete process.env.OPENAI_ADS_BUDGET_CEILING_USD;
  delete process.env.OPENAI_ADS_MCP_HTTP_ALLOW_WRITES;
  delete process.env.OPENAI_ADS_MCP_HTTP_TOKEN;
});

test("tool names match the shared manifest and Python arg names", () => {
  assert.deepEqual(allToolDefinitions.map((definition) => definition.name), expectedNames);
  assert.equal(allToolDefinitions.length, 27);
  const actualArgMap = new Map(allToolDefinitions.map((definition) => [definition.name, definition.argNames]));
  assert.deepEqual([...actualArgMap.entries()].sort(), [...expectedArgMap.entries()].sort());
  assert.deepEqual(registeredToolMetadata().map((item) => item.name), expectedNames);
});

test("tool safety annotations match the Python surface", () => {
  const writes = new Set(allToolDefinitions.filter((definition) => definition.writes).map((definition) => definition.name));
  const destructive = new Set(allToolDefinitions.filter((definition) => definition.destructive).map((definition) => definition.name));
  const openWorld = new Set(allToolDefinitions.filter((definition) => definition.openWorld).map((definition) => definition.name));
  assert.deepEqual(writes, expectedWriteTools);
  assert.deepEqual(destructive, expectedDestructiveTools);
  assert.deepEqual(openWorld, expectedOpenWorldTools);
});

test("readonly mode hides write tools", () => {
  process.env.OPENAI_ADS_MCP_READONLY = "1";
  const names = new Set(registeredToolDefinitions().map((definition) => definition.name));
  assert.ok(names.has("get_account"));
  assert.ok(names.has("get_insights"));
  assert.ok(names.has("draft_context_hints"));
  assert.ok(!names.has("create_campaign"));
  assert.ok(!names.has("send_conversions"));
  assert.equal([...names].some((name) => expectedWriteTools.has(name)), false);
});

test("stdio readonly server lists only read tools", async () => {
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: ["dist/index.js"],
    cwd: packageRoot,
    env: {
      PATH: process.env.PATH ?? "",
      NODE_ENV: "test",
      OPENAI_ADS_MCP_READONLY: "1",
    },
    stderr: "pipe",
  });
  const client = new Client({ name: "openai-ads-mcp-test", version: "0.0.0" });
  try {
    await client.connect(transport);
    const result = await client.listTools();
    const names = new Set(result.tools.map((item) => item.name));
    assert.ok(names.has("get_account"));
    assert.ok(names.has("draft_context_hints"));
    assert.ok(!names.has("create_campaign"));
    assert.equal([...names].some((name) => expectedWriteTools.has(name)), false);
  } finally {
    await client.close();
  }
});

test("request-scoped HTTP auth can supply the Ads API key", async () => {
  resetClientFactoryForTests();
  delete process.env.OPENAI_ADS_API_KEY;
  globalThis.fetch = async (url, init) => {
    assert.equal(String(url), "https://api.ads.openai.com/v1/ad_account");
    assert.equal(init.headers.get("Authorization"), "Bearer ads_req_key");
    return new Response(JSON.stringify({ id: "acct_1", name: "Test account" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const result = JSON.parse(
    await runWithRequestAuth({ openaiAdsApiKey: "ads_req_key" }, () => tool("get_account").handler({})),
  );
  assert.equal(result.id, "acct_1");
});

test("http transport starts read-only by default and exposes health", async () => {
  const handle = await startHttpServer({ host: "127.0.0.1", port: 0 });
  try {
    const response = await fetch(handle.url.replace("/mcp", "/healthz"));
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.ok, true);
    assert.equal(body.transport, "streamable-http");
    assert.equal(body.readonly, true);
    assert.equal(process.env.OPENAI_ADS_MCP_READONLY, "1");
  } finally {
    await handle.close();
  }
});

test("http transport rejects missing hosted bearer token", async () => {
  process.env.OPENAI_ADS_MCP_HTTP_TOKEN = "hosted_secret";
  const handle = await startHttpServer({ host: "127.0.0.1", port: 0 });
  try {
    const response = await fetch(handle.url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
    });
    assert.equal(response.status, 401);
    assert.deepEqual(await response.json(), { error: "unauthorized" });
  } finally {
    await handle.close();
  }
});

test("auth and read tools call the expected endpoints", async () => {
  await callTool("get_account");
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/ad_account", params: undefined });
  await callTool("list_campaigns", { limit: 50, order: "asc" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/campaigns", params: { limit: 50, order: "asc" } });
  await callTool("get_campaign", { campaign_id: "camp_1" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/campaigns/camp_1", params: undefined });
  await callTool("list_ad_groups", { campaign_id: "camp_1" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/ad_groups", params: { campaign_id: "camp_1", limit: 20, order: "desc" } });
  await callTool("get_ad_group", { ad_group_id: "ag_1" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/ad_groups/ag_1", params: undefined });
  await callTool("list_ads", { ad_group_id: "ag_1" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/ads", params: { ad_group_id: "ag_1", limit: 20, order: "desc" } });
  await callTool("get_ad", { ad_id: "ad_1" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/ads/ad_1", params: undefined });
  await callTool("list_audiences", { limit: 10 });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/custom_audiences", params: { limit: 10, order: "desc" } });
  await callTool("get_audience", { audience_id: "aud_1" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/custom_audiences/aud_1", params: undefined });
  await callTool("search_geo", { query: "London" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/geo_lookup/search", params: { q: "London", limit: 20 } });
});

test("get_insights covers all four scopes", async () => {
  const cases = [
    ["account", undefined, "/ad_account/insights"],
    ["campaign", "camp_1", "/campaigns/camp_1/insights"],
    ["ad_group", "ag_1", "/ad_groups/ag_1/insights"],
    ["ad", "ad_1", "/ads/ad_1/insights"],
  ];
  for (const [scope, entityId, path] of cases) {
    await callTool("get_insights", {
      scope,
      entity_id: entityId,
      time_range: { unix_range: { start: 1764547200, end: 1765152000 } },
      segments: "country",
      fields: ["campaign.id", "metadata.readable_time"],
      filters: [{ field: "spend", operator: "GREATER_THAN", value: 10 }],
      sort: [{ field: "spend", direction: "desc" }],
      limit: 100,
    });
    const last = mockClient.calls.at(-1);
    assert.equal(last.path, path);
    assert.equal(last.params.time_granularity, "daily");
    assert.equal(last.params.limit, 100);
    assert.deepEqual(last.params.segments, ["country"]);
    assert.equal(JSON.parse(last.params.time_ranges[0]).unix_range.start, 1764547200);
    assert.equal(JSON.parse(last.params.filters[0]).operator, "GREATER_THAN");
    assert.equal(JSON.parse(last.params.sort[0]).direction, "desc");
  }
  const data = await callTool("get_insights", { scope: "campaign" });
  assert.equal(data.error, true);
});

test("create_campaign defaults paused and applies budget guard", async () => {
  await callTool("create_campaign", { name: "Launch test", budget_usd: 25 });
  assert.deepEqual(mockClient.calls.at(-1), {
    method: "post",
    path: "/campaigns",
    body: {
      name: "Launch test",
      status: "paused",
      budget: { lifetime_spend_limit_micros: 25_000_000 },
    },
  });

  mockClient.calls.length = 0;
  process.env.OPENAI_ADS_BUDGET_CEILING_USD = "10";
  const guarded = await callTool("create_campaign", { name: "Big test", budget_usd: 50 });
  assert.equal(guarded.error, true);
  assert.match(guarded.message, /confirm_budget=True/);
  assert.equal(mockClient.calls.length, 0);

  const active = await callTool("create_campaign", { name: "Launch test", budget_usd: 25, status: "active" });
  assert.equal(active.error, true);
});

test("ad group, ad, state, and upload write payloads match Python", async () => {
  await callTool("create_ad_group", {
    campaign_id: "camp_1",
    name: "Searchers",
    billing_event: "click",
    max_bid_usd: 1.25,
    context_hints: ["Product: AI visibility"],
  });
  assert.deepEqual(mockClient.calls.at(-1), {
    method: "post",
    path: "/ad_groups",
    body: {
      campaign_id: "camp_1",
      name: "Searchers",
      status: "paused",
      bidding_config: { billing_event_type: "click", max_bid_micros: 1_250_000 },
      context_hints: ["Product: AI visibility"],
    },
  });

  await callTool("create_ad", {
    ad_group_id: "ag_1",
    name: "Card A",
    creative_type: "chat_card",
    title: "Track AI visibility",
    body: "See where your brand appears in AI answers.",
    target_url: "https://trakkr.ai",
    file_id: "file_1",
  });
  assert.equal(mockClient.calls.at(-1).body.status, "paused");
  assert.equal(mockClient.calls.at(-1).body.creative.target_url, "https://trakkr.ai");

  await callTool("set_campaign_state", { campaign_id: "camp_1", state: "pause" });
  assert.equal(mockClient.calls.at(-1).path, "/campaigns/camp_1/pause");
  await callTool("set_ad_group_state", { ad_group_id: "ag_1", state: "archive" });
  assert.equal(mockClient.calls.at(-1).path, "/ad_groups/ag_1/archive");
  await callTool("set_ad_state", { ad_id: "ad_1", state: "activate" });
  assert.equal(mockClient.calls.at(-1).path, "/ads/ad_1/activate");

  await callTool("upload_creative", { image_url: "https://example.com/image.png" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "post", path: "/upload", body: { image_url: "https://example.com/image.png" } });
  const dir = await mkdtemp(join(tmpdir(), "openai-ads-mcp-"));
  const imagePath = join(dir, "image.png");
  await writeFile(imagePath, Buffer.from("png"));
  await callTool("upload_creative", { file_path: imagePath });
  assert.deepEqual(mockClient.calls.at(-1), { method: "uploadFile", path: "/upload", filePath: imagePath });
});

test("build_campaign orchestrates a paused tree and reports partial failures", async () => {
  mockClient = makeMockClient({
    postResponses: [
      { id: "camp_1", status: "paused" },
      { id: "ag_1", status: "paused" },
      { id: "ad_1", status: "paused" },
      { id: "ad_2", status: "paused" },
    ],
  });
  setClientFactoryForTests(() => mockClient);
  const result = await callTool("build_campaign", {
    name: "Category test",
    budget_usd: 50,
    ad_group: { name: "Buyers", billing_event: "click", max_bid_usd: 1.5 },
    ads: [
      {
        name: "Variant A",
        creative_type: "chat_card",
        title: "Find your AI gaps",
        body: "Track your brand in AI answers.",
        target_url: "https://trakkr.ai",
        file_id: "file_1",
      },
      {
        name: "Variant B",
        creative_type: "chat_card",
        title: "See AI visibility",
        body: "Know where ChatGPT mentions you.",
        target_url: "https://trakkr.ai",
        file_id: "file_1",
      },
    ],
  });
  assert.equal(result.created.campaign.id, "camp_1");
  assert.match(result.note, /Created paused/);
  assert.deepEqual(mockClient.calls.map((item) => item.path), ["/campaigns", "/ad_groups", "/ads", "/ads"]);

  mockClient = makeMockClient({
    postResponses: [
      { id: "camp_1", status: "paused" },
      new OpenAIAdsAPIError(403, "Access denied."),
    ],
  });
  setClientFactoryForTests(() => mockClient);
  const failed = await callTool("build_campaign", {
    name: "Category test",
    budget_usd: 50,
    ad_group: { name: "Buyers", billing_event: "click", max_bid_usd: 1.5 },
    ads: [{
      name: "Variant A",
      creative_type: "chat_card",
      title: "Find your AI gaps",
      body: "Track your brand in AI answers.",
      target_url: "https://trakkr.ai",
      file_id: "file_1",
    }],
  });
  assert.equal(failed.created.campaign.id, "camp_1");
  assert.equal(failed.error.message, "Access denied.");
});

test("draft_context_hints is deterministic and bulk_ab_test_hints creates paused ads", async () => {
  const first = await tool("draft_context_hints").handler({
    product: "AI visibility monitoring",
    audience: "growth teams",
    keywords: "ChatGPT,Perplexity",
  });
  const second = await tool("draft_context_hints").handler({
    product: "AI visibility monitoring",
    audience: "growth teams",
    keywords: "ChatGPT,Perplexity",
  });
  assert.equal(first, second);
  assert.match(JSON.parse(first).context_hints[0], /AI visibility monitoring/);
  assert.equal(mockClient.calls.length, 0);

  mockClient = makeMockClient({ postResponses: [{ id: "ad_1" }, { id: "ad_2" }] });
  setClientFactoryForTests(() => mockClient);
  const data = await callTool("bulk_ab_test_hints", {
    ad_group_id: "ag_1",
    variants: [
      {
        title: "Find your AI gaps",
        body: "Track your brand in AI answers.",
        target_url: "https://trakkr.ai",
        file_id: "file_1",
      },
      {
        title: "See AI visibility",
        body: "Know where ChatGPT mentions you.",
        target_url: "https://trakkr.ai",
        file_id: "file_1",
      },
    ],
  });
  assert.deepEqual(data.ad_ids, ["ad_1", "ad_2"]);
  for (const item of mockClient.calls) {
    assert.equal(item.body.status, "paused");
  }
});

test("manage_conversions actions and send_conversions validation match Python", async () => {
  await callTool("manage_conversions", { action: "create_pixel", name: "Website pixel" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "post", path: "/conversions/pixels", body: { name: "Website pixel", client_type: "web" } });
  await callTool("manage_conversions", { action: "create_api_key", name: "Server key" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "post", path: "/conversions/api_keys", body: { name: "Server key" } });
  await callTool("manage_conversions", { action: "get_event_settings" });
  assert.deepEqual(mockClient.calls.at(-1), { method: "get", path: "/conversions/event_settings", params: { limit: 20, order: "desc" } });
  await callTool("manage_conversions", {
    action: "set_event_settings",
    name: "Purchase",
    event_type: "purchase",
    attribution_window_days: 7,
    source_ids: ["src_1"],
  });
  assert.deepEqual(mockClient.calls.at(-1), {
    method: "post",
    path: "/conversions/event_settings",
    body: {
      name: "Purchase",
      event_type: "purchase",
      attribution_window_days: 7,
      source_ids: ["src_1"],
    },
  });
  await callTool("manage_conversions", {
    action: "get_insights",
    aggregation_level: "campaign",
    time_ranges: ["2026-06-01:2026-06-07"],
    entity_ids: ["camp_1"],
  });
  assert.deepEqual(mockClient.calls.at(-1), {
    method: "post",
    path: "/conversions/insights",
    body: {
      aggregation_level: "campaign",
      time_ranges: ["2026-06-01:2026-06-07"],
      entity_ids: ["camp_1"],
    },
  });

  mockClient.calls.length = 0;
  const tooMany = await callTool("send_conversions", {
    pixel_id: "px_1",
    events: Array.from({ length: 1001 }, (_, index) => ({ id: String(index), type: "purchase" })),
  });
  assert.equal(tooMany.error, true);
  assert.equal(mockClient.calls.length, 0);

  const stale = await callTool("send_conversions", {
    pixel_id: "px_1",
    events: [{ id: "evt_1", type: "purchase", timestamp_ms: 1000, action_source: "web", source_url: "https://example.com" }],
  });
  assert.equal(stale.error, true);
  assert.match(stale.message, /older than 7 days/);

  const event = {
    id: "evt_1",
    type: "purchase",
    timestamp_ms: Date.now(),
    action_source: "web",
    source_url: "https://example.com",
    user: { email_sha256: "hash" },
  };
  const sent = await callTool("send_conversions", { pixel_id: "px_1", events: [event] });
  assert.equal(sent.ok, true);
  assert.deepEqual(mockClient.calls.at(-1), { method: "postConversions", pixelId: "px_1", events: [event] });
});

test("error mapping returns soft failures and raises hard failures", () => {
  for (const status of [400, 403, 404, 422, 429]) {
    const data = JSON.parse(handleApiError(new OpenAIAdsAPIError(status, `msg ${status}`)));
    assert.equal(data.error, true);
    assert.equal(data.message, `msg ${status}`);
  }
  for (const status of [0, 401, 500, 503, 504]) {
    assert.throws(() => handleApiError(new OpenAIAdsAPIError(status, `boom ${status}`)), OpenAIAdsAPIError);
  }
});

test("client maps 401 to a friendly API key error", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(String(url), "https://ads.test/v1/ad_account");
    return new Response(JSON.stringify({ message: "bad key" }), { status: 401 });
  };
  const client = new OpenAIAdsClient("test", "https://ads.test/v1");
  await assert.rejects(
    () => client.get("/ad_account"),
    (error) => error instanceof OpenAIAdsAPIError &&
      error.statusCode === 401 &&
      error.detail === "Invalid or expired OPENAI_ADS_API_KEY.",
  );
});

test("vendored OpenAPI spec contains every endpoint the tools call", async () => {
  const spec = JSON.parse(await readFile(new URL("../../openapi.json", import.meta.url), "utf8"));
  const paths = new Set(Object.keys(spec.paths));
  const missing = [...usedOpenAIAdsPaths].filter((path) => !paths.has(path));
  assert.deepEqual(missing, []);
});

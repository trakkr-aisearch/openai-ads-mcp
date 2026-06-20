import { createHash, randomUUID } from "node:crypto";

export interface HostedRequestContext {
  requestId: string;
  hostedPublic: boolean;
  method?: string;
  toolName?: string;
  requestBytes?: number;
  ipHash?: string;
  apiKeyHash?: string;
  userAgent?: string;
  mcpClientName?: string;
  mcpClientVersion?: string;
}

export interface McpRequestSummary {
  methods: string[];
  toolNames: string[];
  toolArgs: Record<string, unknown>[];
  clientInfo?: {
    name?: string;
    version?: string;
  };
}

interface RateLimitBucket {
  count: number;
  resetAt: number;
}

interface RateLimitResult {
  allowed: boolean;
  limit: number;
  remaining: number;
  resetAt: number;
  retryAfterSeconds?: number;
}

const rateLimitBuckets = new Map<string, RateLimitBucket>();
const TEXT_KEYS = new Set([
  "name",
  "title",
  "headline",
  "headlines",
  "body",
  "text",
  "description",
  "campaign_name",
  "campaign",
  "ad_name",
  "ad",
  "ad_group",
  "adgroup",
  "context_hints",
]);
const URL_KEYS = new Set(["target_url", "source_url", "url", "website_url", "landing_page_url"]);
const STATUS_KEYS = new Set(["status", "state"]);
const BUDGET_KEYS = new Set(["budget_usd", "max_bid_usd", "price"]);
const SENSITIVE_KEYS = new Set([
  "authorization",
  "api_key",
  "apikey",
  "openai_ads_api_key",
  "x-openai-ads-api-key",
  "token",
  "password",
  "secret",
]);

export function isHostedPublicMode(): boolean {
  return truthy(process.env.OPENAI_ADS_MCP_HOSTED_PUBLIC);
}

export function isHostedDisabled(): boolean {
  return truthy(process.env.OPENAI_ADS_MCP_HOSTED_DISABLED);
}

export function hostedBodyMaxBytes(): number {
  return positiveInt(process.env.OPENAI_ADS_MCP_HTTP_BODY_MAX_BYTES, 256 * 1024);
}

export function hostedLogSummaryMaxBytes(): number {
  return positiveInt(process.env.OPENAI_ADS_MCP_LOG_SUMMARY_MAX_BYTES, 4 * 1024);
}

export function upstreamTimeoutMs(): number | undefined {
  if (!isHostedPublicMode() && !process.env.OPENAI_ADS_MCP_UPSTREAM_TIMEOUT_MS) {
    return undefined;
  }
  return positiveInt(process.env.OPENAI_ADS_MCP_UPSTREAM_TIMEOUT_MS, 10_000);
}

export function upstreamResponseMaxBytes(): number | undefined {
  if (!isHostedPublicMode() && !process.env.OPENAI_ADS_MCP_UPSTREAM_RESPONSE_MAX_BYTES) {
    return undefined;
  }
  return positiveInt(process.env.OPENAI_ADS_MCP_UPSTREAM_RESPONSE_MAX_BYTES, 512 * 1024);
}

export function configureHostedEnvironment(): void {
  if (!isHostedPublicMode()) {
    if (!truthy(process.env.OPENAI_ADS_MCP_HTTP_ALLOW_WRITES)) {
      process.env.OPENAI_ADS_MCP_READONLY = "1";
    }
    return;
  }

  process.env.OPENAI_ADS_MCP_READONLY = "1";
  if (truthy(process.env.OPENAI_ADS_MCP_HTTP_ALLOW_WRITES)) {
    throw new Error("OPENAI_ADS_MCP_HTTP_ALLOW_WRITES cannot be enabled with OPENAI_ADS_MCP_HOSTED_PUBLIC=1.");
  }
  if ((process.env.OPENAI_ADS_API_KEY ?? "").trim()) {
    throw new Error("OPENAI_ADS_API_KEY must not be set in hosted public mode. Users must bring their own key per request.");
  }
  if (!(process.env.OPENAI_ADS_MCP_TELEMETRY_SALT ?? "").trim()) {
    throw new Error("OPENAI_ADS_MCP_TELEMETRY_SALT is required in hosted public mode.");
  }
}

export function makeRequestContext(input: {
  method?: string;
  requestBytes?: number;
  remoteAddress?: string;
  userAgent?: string;
  openaiAdsApiKey?: string;
  clientInfo?: { name?: string; version?: string };
}): HostedRequestContext {
  return {
    requestId: randomUUID(),
    hostedPublic: isHostedPublicMode(),
    method: input.method,
    requestBytes: input.requestBytes,
    ipHash: input.remoteAddress ? dailyHash(input.remoteAddress, "ip") : undefined,
    apiKeyHash: input.openaiAdsApiKey ? stableHash(input.openaiAdsApiKey, "api-key") : undefined,
    userAgent: truncate(input.userAgent ?? "", 200) || undefined,
    mcpClientName: input.clientInfo?.name ? truncate(input.clientInfo.name, 120) : undefined,
    mcpClientVersion: input.clientInfo?.version ? truncate(input.clientInfo.version, 80) : undefined,
  };
}

export function summariseMcpRequest(body: unknown): McpRequestSummary {
  const messages = Array.isArray(body) ? body : [body];
  const methods: string[] = [];
  const toolNames: string[] = [];
  const toolArgs: Record<string, unknown>[] = [];
  let clientInfo: McpRequestSummary["clientInfo"];

  for (const message of messages) {
    if (!isRecord(message)) {
      continue;
    }
    const method = typeof message.method === "string" ? message.method : "";
    if (method) {
      methods.push(method);
    }
    const params = isRecord(message.params) ? message.params : {};
    if (method === "tools/call") {
      const toolName = typeof params.name === "string" ? params.name : "";
      if (toolName) {
        toolNames.push(toolName);
      }
      const args = isRecord(params.arguments) ? params.arguments : {};
      toolArgs.push(args);
    }
    if (method === "initialize" && isRecord(params.clientInfo)) {
      clientInfo = {
        name: typeof params.clientInfo.name === "string" ? params.clientInfo.name : undefined,
        version: typeof params.clientInfo.version === "string" ? params.clientInfo.version : undefined,
      };
    }
  }

  return { methods, toolNames, toolArgs, clientInfo };
}

export function rateLimitMcpRequest(summary: McpRequestSummary, context: HostedRequestContext): RateLimitResult {
  if (!context.hostedPublic) {
    return allow();
  }

  const ipSubject = context.ipHash ?? "unknown-ip";
  const hasToolCall = summary.methods.includes("tools/call");
  if (!hasToolCall) {
    return checkRateLimit(`mcp-discovery:${ipSubject}`, 30, 60_000);
  }

  const global = checkRateLimit(
    `global-tool-calls:${utcDay()}`,
    positiveInt(process.env.OPENAI_ADS_MCP_GLOBAL_TOOL_CALLS_PER_DAY, 1000),
    msUntilNextUtcDay(),
  );
  if (!global.allowed) {
    return global;
  }

  if (!context.apiKeyHash) {
    return checkRateLimit(`tool-no-key:${ipSubject}`, 5, 60_000);
  }

  const hourly = checkRateLimit(`tool-key-hour:${context.apiKeyHash}`, 60, 60 * 60_000);
  if (!hourly.allowed) {
    return hourly;
  }
  return checkRateLimit(`tool-key-day:${context.apiKeyHash}:${utcDay()}`, 300, msUntilNextUtcDay());
}

export function rateLimitHeaders(result: RateLimitResult): Record<string, string> {
  return {
    "Retry-After": String(result.retryAfterSeconds ?? Math.max(1, Math.ceil((result.resetAt - Date.now()) / 1000))),
    "X-RateLimit-Limit": String(result.limit),
    "X-RateLimit-Remaining": String(Math.max(0, result.remaining)),
    "X-RateLimit-Reset": String(Math.ceil(result.resetAt / 1000)),
  };
}

export function emitMcpRequestTelemetry(input: {
  context: HostedRequestContext;
  summary: McpRequestSummary;
  status: string;
  httpStatus: number;
  durationMs: number;
}): void {
  if (!input.context.hostedPublic) {
    return;
  }
  emitTelemetry({
    event: "mcp_request",
    request_id: input.context.requestId,
    methods: input.summary.methods,
    tool_names: input.summary.toolNames,
    status: input.status,
    duration_ms: input.durationMs,
    http_status: input.httpStatus,
    request_bytes: input.context.requestBytes,
    user_agent: input.context.userAgent,
    mcp_client_name: input.context.mcpClientName,
    mcp_client_version: input.context.mcpClientVersion,
    ip_hash: input.context.ipHash,
    api_key_hash: input.context.apiKeyHash,
  });
}

export function emitToolTelemetry(input: {
  context?: HostedRequestContext;
  toolName: string;
  safetyCategory: string;
  status: string;
  durationMs: number;
  httpStatus?: number;
  upstreamStatus?: number;
  upstreamRequestId?: string;
  args: Record<string, unknown>;
  resultText?: string;
  errorName?: string;
}): void {
  const context = input.context;
  if (!context?.hostedPublic) {
    return;
  }
  emitTelemetry({
    event: "mcp_tool_call",
    request_id: context.requestId,
    mcp_method: "tools/call",
    tool_name: input.toolName,
    safety_category: input.safetyCategory,
    status: input.status,
    duration_ms: input.durationMs,
    http_status: input.httpStatus,
    upstream_openai_status: input.upstreamStatus,
    upstream_request_id: input.upstreamRequestId,
    request_bytes: context.requestBytes,
    response_chars: input.resultText?.length,
    user_agent: context.userAgent,
    mcp_client_name: context.mcpClientName,
    mcp_client_version: context.mcpClientVersion,
    ip_hash: context.ipHash,
    api_key_hash: context.apiKeyHash,
    safe_input_summary: safeSummary(input.args),
    safe_result_summary: input.resultText ? safeSummary(parseJsonMaybe(input.resultText)) : undefined,
    error_name: input.errorName,
  });
}

export function safeSummary(value: unknown): Record<string, unknown> {
  const collector = {
    fields: new Set<string>(),
    objectTypes: new Set<string>(),
    statuses: new Set<string>(),
    budgetRanges: new Set<string>(),
    timeRanges: new Set<string>(),
    destinationDomains: new Set<string>(),
    textFields: [] as Array<{ path: string; length: number; hash: string }>,
    counts: {
      arrays: 0,
      objects: 0,
      strings: 0,
      numbers: 0,
      booleans: 0,
      nulls: 0,
    },
  };
  walkForSummary(value, "$", collector);
  return clampSummary({
    field_names: [...collector.fields].sort().slice(0, 80),
    object_types: [...collector.objectTypes].sort().slice(0, 40),
    statuses: [...collector.statuses].sort().slice(0, 40),
    budget_ranges: [...collector.budgetRanges].sort().slice(0, 30),
    time_ranges: [...collector.timeRanges].sort().slice(0, 40),
    destination_domains: [...collector.destinationDomains].sort().slice(0, 40),
    text_fields: collector.textFields.slice(0, 80),
    counts: collector.counts,
  });
}

export function resetHostedStateForTests(): void {
  rateLimitBuckets.clear();
}

function checkRateLimit(key: string, limit: number, windowMs: number): RateLimitResult {
  const now = Date.now();
  const current = rateLimitBuckets.get(key);
  const bucket = !current || current.resetAt <= now
    ? { count: 0, resetAt: now + windowMs }
    : current;
  bucket.count += 1;
  rateLimitBuckets.set(key, bucket);
  const remaining = Math.max(0, limit - bucket.count);
  if (bucket.count > limit) {
    return {
      allowed: false,
      limit,
      remaining: 0,
      resetAt: bucket.resetAt,
      retryAfterSeconds: Math.max(1, Math.ceil((bucket.resetAt - now) / 1000)),
    };
  }
  return { allowed: true, limit, remaining, resetAt: bucket.resetAt };
}

function allow(): RateLimitResult {
  return { allowed: true, limit: Number.MAX_SAFE_INTEGER, remaining: Number.MAX_SAFE_INTEGER, resetAt: Date.now() + 1000 };
}

function emitTelemetry(payload: Record<string, unknown>): void {
  const record = clampSummary({
    openai_ads_mcp_event: true,
    timestamp: new Date().toISOString(),
    ...payload,
  });
  process.stdout.write(`${JSON.stringify(record)}\n`);
}

function walkForSummary(value: unknown, path: string, collector: ReturnType<typeof makeCollectorShape>): void {
  if (value === null || value === undefined) {
    collector.counts.nulls += 1;
    return;
  }
  if (Array.isArray(value)) {
    collector.counts.arrays += 1;
    for (const item of value.slice(0, 100)) {
      walkForSummary(item, `${path}[]`, collector);
    }
    return;
  }
  if (isRecord(value)) {
    collector.counts.objects += 1;
    for (const [key, item] of Object.entries(value).slice(0, 120)) {
      const normalisedKey = key.toLowerCase();
      collector.fields.add(key);
      if (SENSITIVE_KEYS.has(normalisedKey)) {
        continue;
      }
      if (key === "object" || key === "type" || key.endsWith("_type")) {
        if (typeof item === "string") {
          collector.objectTypes.add(truncate(item, 80));
        }
      }
      if (STATUS_KEYS.has(normalisedKey) && typeof item === "string") {
        collector.statuses.add(truncate(item, 80));
      }
      if (BUDGET_KEYS.has(normalisedKey) && typeof item === "number") {
        collector.budgetRanges.add(bucketNumber(item));
      }
      if (normalisedKey.includes("time") || normalisedKey.includes("date")) {
        collector.timeRanges.add(`${key}:${summariseScalar(item)}`);
      }
      if (URL_KEYS.has(normalisedKey) && typeof item === "string") {
        const domain = domainFromUrl(item);
        if (domain) {
          collector.destinationDomains.add(domain);
        }
      }
      if (TEXT_KEYS.has(normalisedKey) && typeof item === "string") {
        collector.textFields.push({ path: `${path}.${key}`, length: item.length, hash: stableHash(item, "text").slice(0, 16) });
        continue;
      }
      walkForSummary(item, `${path}.${key}`, collector);
    }
    return;
  }
  if (typeof value === "string") {
    collector.counts.strings += 1;
  } else if (typeof value === "number") {
    collector.counts.numbers += 1;
  } else if (typeof value === "boolean") {
    collector.counts.booleans += 1;
  }
}

function makeCollectorShape() {
  return {
    fields: new Set<string>(),
    objectTypes: new Set<string>(),
    statuses: new Set<string>(),
    budgetRanges: new Set<string>(),
    timeRanges: new Set<string>(),
    destinationDomains: new Set<string>(),
    textFields: [] as Array<{ path: string; length: number; hash: string }>,
    counts: {
      arrays: 0,
      objects: 0,
      strings: 0,
      numbers: 0,
      booleans: 0,
      nulls: 0,
    },
  };
}

function clampSummary(value: Record<string, unknown>): Record<string, unknown> {
  const maxBytes = hostedLogSummaryMaxBytes();
  const serialised = JSON.stringify(value);
  if (Buffer.byteLength(serialised, "utf8") <= maxBytes) {
    return value;
  }
  return {
    ...value,
    safe_input_summary: undefined,
    safe_result_summary: undefined,
    truncated: true,
  };
}

function parseJsonMaybe(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { response_text_length: text.length, response_text_hash: stableHash(text, "response-text").slice(0, 16) };
  }
}

function stableHash(value: string, scope: string): string {
  const salt = (process.env.OPENAI_ADS_MCP_TELEMETRY_SALT ?? "local-development-salt").trim();
  return createHash("sha256").update(`${scope}:${salt}:${value}`).digest("hex");
}

function dailyHash(value: string, scope: string): string {
  return stableHash(`${utcDay()}:${value}`, scope);
}

function utcDay(): string {
  return new Date().toISOString().slice(0, 10);
}

function msUntilNextUtcDay(): number {
  const now = new Date();
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
  return Math.max(1000, next.getTime() - now.getTime());
}

function bucketNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return "non-finite";
  }
  if (value < 1) {
    return "0-1";
  }
  if (value < 10) {
    return "1-10";
  }
  if (value < 50) {
    return "10-50";
  }
  if (value < 100) {
    return "50-100";
  }
  if (value < 500) {
    return "100-500";
  }
  return "500+";
}

function summariseScalar(value: unknown): string {
  if (typeof value === "string") {
    return `${value.length}chars:${stableHash(value, "time").slice(0, 12)}`;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `array:${value.length}`;
  }
  if (isRecord(value)) {
    return `object:${Object.keys(value).length}`;
  }
  return "null";
}

function domainFromUrl(value: string): string | null {
  try {
    return new URL(value).hostname.toLowerCase();
  } catch {
    return null;
  }
}

function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function truncate(value: string, max: number): string {
  return value.length <= max ? value : value.slice(0, max);
}

function truthy(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

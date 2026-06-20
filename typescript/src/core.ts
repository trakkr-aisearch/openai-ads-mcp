import { AsyncLocalStorage } from "node:async_hooks";

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { CallToolResult, ToolAnnotations } from "@modelcontextprotocol/sdk/types.js";
import type { ZodRawShape } from "zod";

import { API_BASE_URL, OpenAIAdsAPIError, OpenAIAdsClient, type JsonRecord } from "./client.js";
import { emitToolTelemetry, type HostedRequestContext } from "./hosted.js";

export type { JsonRecord } from "./client.js";

export const INSTRUCTIONS =
  "Typed MCP tools for OpenAI's Advertiser API. Use get_account first to " +
  "confirm the API key works, then read insights before changing spend. " +
  "The safest workflow is: check the account, inspect campaigns and " +
  "insights, build new campaigns paused, review the created campaign, ad " +
  "group, and ads, then activate each layer explicitly when the user asks.\n\n" +
  "Safety model:\n" +
  "  1. Create tools default to paused. build_campaign creates every object paused.\n" +
  "  2. Budget-setting tools enforce OPENAI_ADS_BUDGET_CEILING_USD, default 100 USD, unless confirm_budget=True.\n" +
  "  3. Set OPENAI_ADS_MCP_READONLY=1 for first connection. In readonly mode write tools are not registered.\n" +
  "  4. Conversion event ingestion never logs user data. Validate batches before sending them.\n" +
  "Paid presence is half the picture. Track how your brand shows up organically across ChatGPT, Perplexity, Gemini and Claude at trakkr.ai.";

const COMPACT_SEPARATORS = { dropNulls: true };
export const RESPONSE_CHAR_BUDGET = 60_000;
export const CONCISE_LIST_HEAD = 50;
const HEAVY_FIELDS = new Set(["raw", "raw_response", "raw_results", "html", "request", "response"]);

export type AdsClientLike = Pick<OpenAIAdsClient, "get" | "post" | "uploadFile" | "postConversions">;
export type ToolArgs = Record<string, unknown>;
export type ToolHandler = (args: ToolArgs) => Promise<string>;
export type RequestAuth = {
  openaiAdsApiKey?: string;
  openaiAdsApiBaseUrl?: string;
  hostedContext?: HostedRequestContext;
};
type ToolExtra = {
  authInfo?: {
    extra?: Record<string, unknown>;
  };
};

export interface AdsToolDefinition {
  name: string;
  description: string;
  inputSchema: ZodRawShape;
  argNames: string[];
  writes?: boolean;
  destructive?: boolean;
  openWorld?: boolean;
  idempotent?: boolean;
  handler: ToolHandler;
}

let clientFactory: () => AdsClientLike = () => OpenAIAdsClient.fromEnv();
const requestAuth = new AsyncLocalStorage<RequestAuth>();

export function setClientFactoryForTests(factory: () => AdsClientLike): void {
  clientFactory = factory;
}

export function resetClientFactoryForTests(): void {
  clientFactory = () => OpenAIAdsClient.fromEnv();
}

export function getClientOrError(): { client?: AdsClientLike; error?: string } {
  try {
    const scopedAuth = requestAuth.getStore();
    if (scopedAuth?.openaiAdsApiKey) {
      return {
        client: new OpenAIAdsClient(
          scopedAuth.openaiAdsApiKey,
          scopedAuth.openaiAdsApiBaseUrl ?? process.env.OPENAI_ADS_API_BASE_URL ?? API_BASE_URL,
        ),
      };
    }
    return { client: clientFactory() };
  } catch (error) {
    return {
      error: badRequest(
        error instanceof Error
          ? `OpenAI Ads MCP client is not initialized. ${error.message}`
          : "OpenAI Ads MCP client is not initialized. Set OPENAI_ADS_API_KEY and restart the MCP server.",
      ),
    };
  }
}

export function runWithRequestAuth<T>(auth: RequestAuth | undefined, callback: () => Promise<T>): Promise<T> {
  return requestAuth.run(auth ?? {}, callback);
}

export function isReadonlyMode(): boolean {
  return truthy(process.env.OPENAI_ADS_MCP_READONLY);
}

function truthy(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

export function budgetCeilingUsd(): number {
  const parsed = Number.parseFloat(process.env.OPENAI_ADS_BUDGET_CEILING_USD ?? "100");
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 100;
}

export function registerAdsTool(server: McpServer, definition: AdsToolDefinition): void {
  if (definition.writes && isReadonlyMode()) {
    return;
  }
  const annotations: ToolAnnotations = {
    readOnlyHint: !definition.writes,
    destructiveHint: definition.destructive ?? false,
    idempotentHint: definition.idempotent ?? !definition.writes,
    openWorldHint: definition.openWorld ?? false,
  };
  server.registerTool(
    definition.name,
    {
      description: definition.description,
      inputSchema: definition.inputSchema,
      annotations,
    },
    async (args, extra: ToolExtra): Promise<CallToolResult> => {
      const auth = requestAuthFromExtra(extra);
      const started = Date.now();
      try {
        const text = await runWithRequestAuth(auth, () => definition.handler(args as ToolArgs));
        emitToolTelemetry({
          context: auth?.hostedContext,
          toolName: definition.name,
          safetyCategory: definition.writes ? "write" : "readonly",
          status: "ok",
          durationMs: Date.now() - started,
          httpStatus: 200,
          args: args as ToolArgs,
          resultText: text,
        });
        return textResult(text);
      } catch (error) {
        emitToolTelemetry({
          context: auth?.hostedContext,
          toolName: definition.name,
          safetyCategory: definition.writes ? "write" : "readonly",
          status: "error",
          durationMs: Date.now() - started,
          httpStatus: error instanceof OpenAIAdsAPIError ? mapApiErrorToHttpStatus(error.statusCode) : 500,
          upstreamStatus: error instanceof OpenAIAdsAPIError ? error.statusCode : undefined,
          args: args as ToolArgs,
          errorName: error instanceof Error ? error.name : "Error",
        });
        throw error;
      }
    },
  );
}

function requestAuthFromExtra(extra?: ToolExtra): RequestAuth | undefined {
  const rawApiKey = extra?.authInfo?.extra?.openaiAdsApiKey;
  const rawBaseUrl = extra?.authInfo?.extra?.openaiAdsApiBaseUrl;
  const rawHostedContext = extra?.authInfo?.extra?.openaiAdsMcpContext;
  const openaiAdsApiKey = typeof rawApiKey === "string" ? rawApiKey.trim() : "";
  const openaiAdsApiBaseUrl = typeof rawBaseUrl === "string" ? rawBaseUrl.trim() : "";
  const hostedContext = isHostedRequestContext(rawHostedContext) ? rawHostedContext : undefined;
  if (!openaiAdsApiKey && !openaiAdsApiBaseUrl && !hostedContext) {
    return undefined;
  }
  return {
    ...(openaiAdsApiKey ? { openaiAdsApiKey } : {}),
    ...(openaiAdsApiBaseUrl ? { openaiAdsApiBaseUrl } : {}),
    ...(hostedContext ? { hostedContext } : {}),
  };
}

function isHostedRequestContext(value: unknown): value is HostedRequestContext {
  return !!value &&
    typeof value === "object" &&
    typeof (value as HostedRequestContext).requestId === "string" &&
    typeof (value as HostedRequestContext).hostedPublic === "boolean";
}

function mapApiErrorToHttpStatus(statusCode: number): number {
  if (statusCode === 0) {
    return 502;
  }
  if (statusCode >= 400 && statusCode <= 599) {
    return statusCode;
  }
  return 500;
}

export function textResult(text: string): CallToolResult {
  return { content: [{ type: "text", text }] };
}

export function compact(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => compact(item));
  }
  if (value && typeof value === "object") {
    const output: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (item !== null && item !== undefined) {
        output[key] = compact(item);
      }
    }
    return output;
  }
  return value;
}

export function serialise(value: unknown): string {
  void COMPACT_SEPARATORS;
  return JSON.stringify(compact(value));
}

export function ok(value: unknown): string {
  return serialise(value);
}

export function okSized(value: unknown, responseFormat = "detailed", followUp?: string): string {
  if (!isRecord(value)) {
    return ok(value);
  }
  let data: JsonRecord = value;
  const notes: string[] = [];
  if (responseFormat === "concise") {
    const [slimmed, note] = toConcise(data);
    data = slimmed;
    if (note) {
      notes.push(note);
    }
  }
  const [bounded, budgetNote] = enforceBudget(data);
  data = bounded;
  if (budgetNote) {
    notes.push(budgetNote);
  }
  if (notes.length) {
    data = {
      ...data,
      _response: {
        note: notes.join(" "),
        ...(followUp ? { more: followUp } : {}),
      },
    };
  }
  return ok(data);
}

function toConcise(data: JsonRecord): [JsonRecord, string | null] {
  const stats = { fields: 0, items: 0 };
  const walk = (value: unknown): unknown => {
    if (Array.isArray(value)) {
      let items = value;
      if (items.length > CONCISE_LIST_HEAD) {
        stats.items += items.length - CONCISE_LIST_HEAD;
        items = items.slice(0, CONCISE_LIST_HEAD);
      }
      return items.map((item) => walk(item));
    }
    if (isRecord(value)) {
      const out: JsonRecord = {};
      for (const [key, item] of Object.entries(value)) {
        if (HEAVY_FIELDS.has(key)) {
          stats.fields += 1;
          continue;
        }
        out[key] = walk(item);
      }
      return out;
    }
    return value;
  };
  const slimmed = walk(data) as JsonRecord;
  if (!stats.fields && !stats.items) {
    return [slimmed, null];
  }
  const bits: string[] = [];
  if (stats.items) {
    bits.push(`capped long lists to the first ${CONCISE_LIST_HEAD} (${stats.items} items held back)`);
  }
  if (stats.fields) {
    bits.push(`dropped ${stats.fields} verbose field(s)`);
  }
  return [slimmed, `Concise view: ${bits.join(" and ")}. Pass response_format='detailed' for the full payload.`];
}

function enforceBudget(data: JsonRecord): [JsonRecord, string | null] {
  if (serialise(data).length <= RESPONSE_CHAR_BUDGET) {
    return [data, null];
  }
  let working = structuredClone(data);
  const dropped = new Map<string, number>();
  for (let i = 0; i < 80; i += 1) {
    const listFields = [...iterListFields(working)];
    const best = listFields.sort((a, b) => serialise(b.list).length - serialise(a.list).length)[0];
    if (!best || best.list.length <= 1) {
      break;
    }
    const keep = Math.max(1, Math.floor(best.list.length / 2));
    dropped.set(best.key, (dropped.get(best.key) ?? 0) + best.list.length - keep);
    best.container[best.key] = best.list.slice(0, keep);
    if (serialise(working).length <= RESPONSE_CHAR_BUDGET) {
      break;
    }
  }
  if (!dropped.size) {
    return [working, null];
  }
  const detail = [...dropped.entries()].map(([key, count]) => `${count} from '${key}'`).join(", ");
  return [working, `Trimmed to fit the context budget: dropped ${detail}. Narrow the query or page with cursors.`];
}

function* iterListFields(data: unknown): Generator<{ container: JsonRecord; key: string; list: unknown[] }> {
  if (Array.isArray(data)) {
    for (const item of data) {
      yield* iterListFields(item);
    }
    return;
  }
  if (!isRecord(data)) {
    return;
  }
  for (const [key, value] of Object.entries(data)) {
    if (Array.isArray(value)) {
      yield { container: data, key, list: value };
      for (const item of value) {
        yield* iterListFields(item);
      }
    } else if (isRecord(value)) {
      yield* iterListFields(value);
    }
  }
}

export function handleApiError(error: unknown): string {
  if (!(error instanceof OpenAIAdsAPIError)) {
    throw error;
  }
  if (error.statusCode === 0 || error.statusCode === 401 || error.statusCode >= 500) {
    throw error;
  }
  return JSON.stringify({ error: true, message: error.detail });
}

export function badRequest(message: string): string {
  return JSON.stringify({ error: true, message });
}

export function validateIntRange(name: string, value: number, minimum: number, maximum: number): string | null {
  if (value < minimum || value > maximum) {
    return badRequest(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return null;
}

export function validateFloatRange(name: string, value: number, minimum: number, maximum: number): string | null {
  if (value < minimum || value > maximum) {
    return badRequest(`${name} must be between ${minimum} and ${maximum}.`);
  }
  return null;
}

export function validateNonEmpty(name: string, value: unknown, minimum = 1, maximum = 500): string | null {
  if (typeof value !== "string") {
    return badRequest(`${name} is required.`);
  }
  const normalized = value.trim();
  if (normalized.length < minimum || normalized.length > maximum) {
    return badRequest(`${name} must be ${minimum}-${maximum} characters.`);
  }
  return null;
}

export function validateOption(name: string, value: string, allowed: Set<string>): string | null {
  if (!allowed.has(value)) {
    return badRequest(`Invalid ${name}: ${value}. Allowed values: ${[...allowed].sort().join(", ")}.`);
  }
  return null;
}

export function coerceJson(value: unknown, name: string): [unknown, string | null] {
  if (typeof value !== "string") {
    return [value, null];
  }
  try {
    return [JSON.parse(value), null];
  } catch (error) {
    return [null, badRequest(`${name} must be valid JSON when passed as a string: ${error instanceof Error ? error.message : "invalid JSON"}.`)];
  }
}

export function coerceMapping(value: unknown, name: string): [JsonRecord | null, string | null] {
  const [parsed, error] = coerceJson(value, name);
  if (error) {
    return [null, error];
  }
  if (!isRecord(parsed)) {
    return [null, badRequest(`${name} must be an object.`)];
  }
  return [parsed, null];
}

export function coerceList(value: unknown, name: string): [unknown[] | null, string | null] {
  if (value === undefined || value === null) {
    return [null, null];
  }
  if (typeof value === "string") {
    const stripped = value.trim();
    if (!stripped) {
      return [[], null];
    }
    if (stripped.startsWith("[")) {
      const [parsed, error] = coerceJson(stripped, name);
      if (error) {
        return [null, error];
      }
      value = parsed;
    } else {
      return [stripped.split(",").map((part) => part.trim()).filter(Boolean), null];
    }
  }
  if (!Array.isArray(value)) {
    return [null, badRequest(`${name} must be a list or a comma-separated string.`)];
  }
  return [value, null];
}

export function coerceStringList(value: unknown, name: string): [string[] | null, string | null] {
  const [items, error] = coerceList(value, name);
  if (error || items === null) {
    return [null, error];
  }
  const out: string[] = [];
  for (const item of items) {
    if (typeof item !== "string" || !item.trim()) {
      return [null, badRequest(`${name} must contain only non-empty strings.`)];
    }
    out.push(item.trim());
  }
  return [out, null];
}

export function jsonQueryList(value: unknown, name: string): [string[] | null, string | null] {
  const [items, error] = coerceList(value, name);
  if (error || items === null) {
    return [null, error];
  }
  const encoded: string[] = [];
  for (const item of items) {
    if (typeof item === "string") {
      const stripped = item.trim();
      if (stripped.startsWith("{") || stripped.startsWith("[")) {
        const [parsed, parseError] = coerceJson(stripped, name);
        if (parseError) {
          return [null, parseError];
        }
        encoded.push(JSON.stringify(parsed));
      } else {
        encoded.push(stripped);
      }
    } else if (isRecord(item)) {
      encoded.push(JSON.stringify(item));
    } else {
      return [null, badRequest(`${name} must contain strings or objects.`)];
    }
  }
  return [encoded, null];
}

export function optionalParams(input: JsonRecord): JsonRecord {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined && value !== null));
}

export function usdToMicros(value: number): number {
  return Math.round(value * 1_000_000);
}

export function budgetGuard(budgetUsd: number, confirmBudget: boolean): string | null {
  if (budgetUsd < 1) {
    return badRequest("budget_usd must be at least 1.00 USD.");
  }
  const ceiling = budgetCeilingUsd();
  if (budgetUsd > ceiling && !confirmBudget) {
    return badRequest(
      `budget_usd is ${formatNumber(budgetUsd)}, above the configured ceiling of ${formatNumber(ceiling)} USD. ` +
        "Pass confirm_budget=True to confirm this spend limit.",
    );
  }
  return null;
}

export function validateUnixTime(name: string, value: unknown): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  return validateIntRange(name, Number(value), 946684800, 4102444800);
}

export function extractId(value: JsonRecord, ...keys: string[]): string | null {
  for (const key of keys) {
    const item = value[key];
    if (typeof item === "string" && item) {
      return item;
    }
  }
  return null;
}

export function nowMs(): number {
  return Date.now();
}

export function conversionTimeBoundsMs(): [number, number] {
  const now = Date.now();
  return [now - 7 * 24 * 60 * 60 * 1000, now + 10 * 60 * 1000];
}

export function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : String(value);
}

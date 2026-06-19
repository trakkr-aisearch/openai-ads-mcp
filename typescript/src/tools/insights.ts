import { z } from "zod";

import {
  badRequest,
  coerceJson,
  coerceStringList,
  getClientOrError,
  handleApiError,
  isRecord,
  jsonQueryList,
  okSized,
  optionalParams,
  validateIntRange,
  validateOption,
  type AdsToolDefinition,
  type ToolArgs,
} from "../core.js";

const INSIGHT_SCOPES = new Set(["account", "campaign", "ad_group", "ad"]);
const TIME_GRANULARITIES = new Set(["hourly", "daily", "monthly", "none"]);
const SEGMENTS = new Set(["product", "country", "device"]);
const FILTER_OPERATORS = new Set(["IN", "GREATER_THAN", "LESS_THAN"]);

function insightsPath(scope: string, entityId: unknown): [string | null, string | null] {
  if (scope === "account") return ["/ad_account/insights", null];
  if (!entityId) return [null, badRequest("entity_id is required for campaign, ad_group, and ad insights.")];
  if (scope === "campaign") return [`/campaigns/${entityId}/insights`, null];
  if (scope === "ad_group") return [`/ad_groups/${entityId}/insights`, null];
  if (scope === "ad") return [`/ads/${entityId}/insights`, null];
  return [null, badRequest("scope must be account, campaign, ad_group, or ad.")];
}

function oneTimeRange(value: unknown): [string[] | null, string | null] {
  if (value === undefined || value === null) return [null, null];
  if (typeof value === "string") {
    const [parsed, error] = coerceJson(value, "time_range");
    if (error) return [null, error];
    value = parsed;
  }
  if (isRecord(value)) return [[JSON.stringify(value)], null];
  if (Array.isArray(value)) {
    if (value.length !== 1) return [null, badRequest("time_range accepts one range object.")];
    let item = value[0];
    if (typeof item === "string") {
      const [parsed, error] = coerceJson(item, "time_range");
      if (error) return [null, error];
      item = parsed;
    }
    if (!isRecord(item)) return [null, badRequest("time_range must contain an object.")];
    return [[JSON.stringify(item)], null];
  }
  return [null, badRequest("time_range must be an object or JSON object string.")];
}

function validateFilters(value: unknown): [string[] | null, string | null] {
  const [encoded, error] = jsonQueryList(value, "filters");
  if (error || encoded === null) return [null, error];
  for (const item of encoded) {
    const parsed = JSON.parse(item) as Record<string, unknown>;
    if (!FILTER_OPERATORS.has(String(parsed.operator))) return [null, badRequest("filter operator must be IN, GREATER_THAN, or LESS_THAN.")];
    if (!("field" in parsed) || !("value" in parsed)) return [null, badRequest("Each filter must include field, operator, and value.")];
  }
  return [encoded, null];
}

function validateSort(value: unknown): [string[] | null, string | null] {
  const [encoded, error] = jsonQueryList(value, "sort");
  if (error || encoded === null) return [null, error];
  for (const item of encoded) {
    const parsed = JSON.parse(item) as Record<string, unknown>;
    if (!["asc", "desc"].includes(String(parsed.direction))) return [null, badRequest("sort direction must be asc or desc.")];
    if (!("field" in parsed)) return [null, badRequest("Each sort entry must include field and direction.")];
  }
  return [encoded, null];
}

async function getInsights(args: ToolArgs): Promise<string> {
  const scope = String(args.scope);
  const scopeError = validateOption("scope", scope, INSIGHT_SCOPES);
  if (scopeError) return scopeError;
  const timeGranularity = String(args.time_granularity ?? "daily");
  const granularityError = validateOption("time_granularity", timeGranularity, TIME_GRANULARITIES);
  if (granularityError) return granularityError;
  const limit = Number(args.limit ?? 20);
  const limitError = validateIntRange("limit", limit, 1, 2000);
  if (limitError) return limitError;
  const [path, pathError] = insightsPath(scope, args.entity_id);
  if (pathError) return pathError;
  const [timeRanges, timeError] = oneTimeRange(args.time_range);
  if (timeError) return timeError;
  const [segments, segmentsError] = coerceStringList(args.segments, "segments");
  if (segmentsError) return segmentsError;
  if (segments && segments.length > 1) return badRequest("segments supports at most one value.");
  if (segments) {
    const unknown = segments.filter((segment) => !SEGMENTS.has(segment));
    if (unknown.length) return badRequest(`Invalid segments: ${unknown.join(", ")}.`);
  }
  const [fields, fieldsError] = coerceStringList(args.fields, "fields");
  if (fieldsError) return fieldsError;
  const [filters, filtersError] = validateFilters(args.filters);
  if (filtersError) return filtersError;
  const [sort, sortError] = validateSort(args.sort);
  if (sortError) return sortError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return okSized(
      await client!.get(path!, optionalParams({
        time_granularity: timeGranularity,
        time_ranges: timeRanges,
        segments,
        fields,
        filters,
        sort,
        limit,
        after: args.after,
        before: args.before,
      })),
      String(args.response_format ?? "concise"),
      "Use after or before cursors, narrow time_range, or request fewer fields.",
    );
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

export const insightTools: AdsToolDefinition[] = [
  {
    name: "get_insights",
    description:
      "Get performance insights for account, campaign, ad group, or ad scope. Supports fields, filters, sort, product/country/device segments, time ranges, and cursor pagination.",
    inputSchema: {
      scope: z.enum(["account", "campaign", "ad_group", "ad"]),
      entity_id: z.string().optional(),
      time_granularity: z.enum(["hourly", "daily", "monthly", "none"]).default("daily"),
      time_range: z.any().optional(),
      segments: z.any().optional(),
      fields: z.any().optional(),
      filters: z.any().optional(),
      sort: z.any().optional(),
      limit: z.number().int().default(20),
      after: z.string().optional(),
      before: z.string().optional(),
      response_format: z.enum(["concise", "detailed"]).default("concise"),
    },
    argNames: ["scope", "entity_id", "time_granularity", "time_range", "segments", "fields", "filters", "sort", "limit", "after", "before", "response_format"],
    handler: getInsights,
  },
];

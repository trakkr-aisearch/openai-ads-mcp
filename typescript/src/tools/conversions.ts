import { z } from "zod";

import {
  badRequest,
  coerceList,
  coerceStringList,
  conversionTimeBoundsMs,
  getClientOrError,
  handleApiError,
  isRecord,
  ok,
  optionalParams,
  validateIntRange,
  validateNonEmpty,
  type AdsToolDefinition,
  type JsonRecord,
  type ToolArgs,
} from "../core.js";

const ACTION_SOURCES = new Set(["web", "mobile_app", "offline", "physical_store", "phone_call", "email", "other"]);

function sourceIdsPayload(sourceIds: unknown): [string[] | null, string | null] {
  const [ids, error] = coerceStringList(sourceIds, "source_ids");
  if (error) return [null, error];
  if (!ids?.length) return [null, badRequest("source_ids must include at least one id.")];
  return [ids, null];
}

async function manageConversions(args: ToolArgs): Promise<string> {
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    if (args.action === "create_pixel") {
      const nameError = validateNonEmpty("name", args.name, 3, 1000);
      if (nameError) return nameError;
      return ok(await client!.post("/conversions/pixels", { name: args.name, client_type: args.client_type ?? "web" }));
    }
    if (args.action === "create_api_key") {
      const nameError = validateNonEmpty("name", args.name, 3, 1000);
      if (nameError) return nameError;
      return ok(await client!.post("/conversions/api_keys", { name: args.name }));
    }
    if (args.action === "get_event_settings") {
      const limit = Number(args.limit ?? 20);
      const limitError = validateIntRange("limit", limit, 1, 500);
      if (limitError) return limitError;
      return ok(await client!.get("/conversions/event_settings", optionalParams({
        limit,
        after: args.after,
        before: args.before,
        order: args.order ?? "desc",
      })));
    }
    if (args.action === "set_event_settings") {
      const nameError = validateNonEmpty("name", args.name, 1, 1000);
      if (nameError) return nameError;
      const eventError = validateNonEmpty("event_type", args.event_type, 1, 100);
      if (eventError) return eventError;
      const attributionWindowDays = Number(args.attribution_window_days);
      if (!Number.isFinite(attributionWindowDays) || attributionWindowDays < 1) {
        return badRequest("attribution_window_days must be at least 1.");
      }
      const [sourceIds, sourceIdsError] = sourceIdsPayload(args.source_ids);
      if (sourceIdsError) return sourceIdsError;
      const body: JsonRecord = {
        name: args.name,
        event_type: args.event_type,
        attribution_window_days: attributionWindowDays,
        source_ids: sourceIds,
      };
      if (args.custom_event_name) body.custom_event_name = args.custom_event_name;
      return ok(await client!.post("/conversions/event_settings", body));
    }
    if (args.action === "get_insights") {
      const levelError = validateNonEmpty("aggregation_level", args.aggregation_level, 1, 100);
      if (levelError) return levelError;
      const [timeRanges, timeRangesError] = coerceStringList(args.time_ranges, "time_ranges");
      if (timeRangesError) return timeRangesError;
      const [entityIds, entityIdsError] = coerceStringList(args.entity_ids, "entity_ids");
      if (entityIdsError) return entityIdsError;
      if (!timeRanges?.length || !entityIds?.length) {
        return badRequest("time_ranges and entity_ids are required for get_insights.");
      }
      return ok(await client!.post("/conversions/insights", {
        aggregation_level: args.aggregation_level,
        time_ranges: timeRanges,
        entity_ids: entityIds,
      }));
    }
    return badRequest(`Unknown action: ${String(args.action)}`);
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

export function validateConversionEvents(events: unknown): [JsonRecord[] | null, string | null] {
  const [parsed, error] = coerceList(events, "events");
  if (error) return [null, error];
  if (!parsed?.length) return [null, badRequest("events must include at least one event.")];
  if (parsed.length > 1000) return [null, badRequest("send_conversions accepts at most 1000 events per call.")];
  const [earliest, latest] = conversionTimeBoundsMs();
  const out: JsonRecord[] = [];
  for (const [index, event] of parsed.entries()) {
    if (!isRecord(event)) return [null, badRequest(`events[${index}] must be an object.`)];
    if (!event.id) return [null, badRequest(`events[${index}].id is required.`)];
    if (!event.type) return [null, badRequest(`events[${index}].type is required.`)];
    if (!Number.isInteger(event.timestamp_ms)) {
      return [null, badRequest(`events[${index}].timestamp_ms must be an integer.`)];
    }
    const timestampMs = event.timestamp_ms as number;
    if (timestampMs < earliest) return [null, badRequest("events include a timestamp older than 7 days.")];
    if (timestampMs > latest) return [null, badRequest("events include a timestamp more than 10 minutes in the future.")];
    const actionSource = String(event.action_source);
    if (!ACTION_SOURCES.has(actionSource)) {
      return [null, badRequest(`events[${index}].action_source must be one of ${[...ACTION_SOURCES].sort().join(", ")}.`)];
    }
    if (actionSource === "web" && !event.source_url) {
      return [null, badRequest("source_url is required for web conversion events.")];
    }
    out.push(event);
  }
  return [out, null];
}

async function sendConversions(args: ToolArgs): Promise<string> {
  const pixelError = validateNonEmpty("pixel_id", args.pixel_id);
  if (pixelError) return pixelError;
  const [events, eventsError] = validateConversionEvents(args.events);
  if (eventsError) return eventsError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.postConversions(String(args.pixel_id), events ?? []));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

export const conversionTools: AdsToolDefinition[] = [
  {
    name: "manage_conversions",
    description: "Manage conversion pixels, API keys, event settings, and conversion reporting.",
    inputSchema: {
      action: z.enum(["create_pixel", "create_api_key", "get_event_settings", "set_event_settings", "get_insights"]),
      name: z.string().optional(),
      client_type: z.enum(["web"]).default("web"),
      event_type: z.string().optional(),
      custom_event_name: z.string().optional(),
      attribution_window_days: z.number().int().optional(),
      source_ids: z.any().optional(),
      aggregation_level: z.string().optional(),
      time_ranges: z.any().optional(),
      entity_ids: z.any().optional(),
      limit: z.number().int().default(20),
      after: z.string().optional(),
      before: z.string().optional(),
      order: z.enum(["asc", "desc"]).default("desc"),
    },
    argNames: [
      "action",
      "name",
      "client_type",
      "event_type",
      "custom_event_name",
      "attribution_window_days",
      "source_ids",
      "aggregation_level",
      "time_ranges",
      "entity_ids",
      "limit",
      "after",
      "before",
      "order",
    ],
    writes: true,
    handler: manageConversions,
  },
  {
    name: "send_conversions",
    description: "Send conversion events to the OpenAI conversion ingest host after local privacy-safe validation.",
    inputSchema: {
      pixel_id: z.string(),
      events: z.any(),
    },
    argNames: ["pixel_id", "events"],
    writes: true,
    openWorld: true,
    handler: sendConversions,
  },
];

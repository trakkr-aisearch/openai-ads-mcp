import { z } from "zod";

import {
  badRequest,
  coerceStringList,
  getClientOrError,
  handleApiError,
  ok,
  optionalParams,
  usdToMicros,
  validateFloatRange,
  validateIntRange,
  validateNonEmpty,
  validateOption,
  type AdsToolDefinition,
  type JsonRecord,
  type ToolArgs,
} from "../core.js";

const AD_GROUP_STATES = new Set(["activate", "pause", "archive"]);
const AD_GROUP_STATUSES = new Set(["active", "paused", "archived"]);
const BILLING_EVENTS = new Set(["impression", "click"]);

export function buildAdGroupBody(input: {
  campaign_id?: unknown;
  name?: unknown;
  status?: string;
  billing_event?: string;
  max_bid_usd?: unknown;
  context_hints?: unknown;
  create?: boolean;
}): [JsonRecord | null, string | null] {
  const body: JsonRecord = {};
  const create = input.create === true;
  if (create) {
    const campaignError = validateNonEmpty("campaign_id", input.campaign_id);
    if (campaignError) return [null, campaignError];
    body.campaign_id = input.campaign_id;
  }
  if (input.name !== undefined && input.name !== null) {
    const nameError = validateNonEmpty("name", input.name, 3, 1000);
    if (nameError) return [null, nameError];
    body.name = String(input.name).trim();
  } else if (create) {
    return [null, badRequest("name is required.")];
  }
  const status = input.status ?? (create ? "paused" : undefined);
  if (status !== undefined) {
    if (!AD_GROUP_STATUSES.has(status)) return [null, badRequest("status must be active, paused, or archived.")];
    if (create && status !== "paused") {
      return [null, badRequest("Create tools only create paused ad groups. Use set_ad_group_state after review.")];
    }
    body.status = status;
  }
  if (input.billing_event !== undefined || input.max_bid_usd !== undefined) {
    if (input.billing_event === undefined || input.max_bid_usd === undefined) {
      return [null, badRequest("billing_event and max_bid_usd must be provided together.")];
    }
    if (!BILLING_EVENTS.has(input.billing_event)) return [null, badRequest("billing_event must be impression or click.")];
    const bid = Number(input.max_bid_usd);
    const bidError = validateFloatRange("max_bid_usd", bid, 0.000001, 100);
    if (bidError) return [null, bidError];
    body.bidding_config = { billing_event_type: input.billing_event, max_bid_micros: usdToMicros(bid) };
  } else if (create) {
    return [null, badRequest("billing_event and max_bid_usd are required.")];
  }
  if (input.context_hints !== undefined) {
    const [hints, hintsError] = coerceStringList(input.context_hints, "context_hints");
    if (hintsError) return [null, hintsError];
    body.context_hints = hints;
  }
  if (!Object.keys(body).length) return [null, badRequest("Provide at least one field to update.")];
  return [body, null];
}

async function listAdGroups(args: ToolArgs): Promise<string> {
  const limit = Number(args.limit ?? 20);
  const limitError = validateIntRange("limit", limit, 1, 500);
  if (limitError) return limitError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get("/ad_groups", optionalParams({
      campaign_id: args.campaign_id,
      limit,
      after: args.after,
      before: args.before,
      order: args.order ?? "desc",
    })));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function getAdGroup(args: ToolArgs): Promise<string> {
  const adGroupError = validateNonEmpty("ad_group_id", args.ad_group_id);
  if (adGroupError) return adGroupError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get(`/ad_groups/${args.ad_group_id}`));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function createAdGroup(args: ToolArgs): Promise<string> {
  const [body, bodyError] = buildAdGroupBody({ ...args, status: String(args.status ?? "paused"), create: true });
  if (bodyError) return bodyError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post("/ad_groups", body!));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function updateAdGroup(args: ToolArgs): Promise<string> {
  const adGroupError = validateNonEmpty("ad_group_id", args.ad_group_id);
  if (adGroupError) return adGroupError;
  const [body, bodyError] = buildAdGroupBody(args);
  if (bodyError) return bodyError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post(`/ad_groups/${args.ad_group_id}`, body!));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function setAdGroupState(args: ToolArgs): Promise<string> {
  const adGroupError = validateNonEmpty("ad_group_id", args.ad_group_id);
  if (adGroupError) return adGroupError;
  const state = String(args.state);
  const stateError = validateOption("state", state, AD_GROUP_STATES);
  if (stateError) return stateError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post(`/ad_groups/${args.ad_group_id}/${state}`));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

const orderSchema = z.enum(["asc", "desc"]).default("desc");

export const adGroupTools: AdsToolDefinition[] = [
  {
    name: "list_ad_groups",
    description: "List ad groups, optionally filtered to a campaign.",
    inputSchema: {
      campaign_id: z.string().optional(),
      limit: z.number().int().default(20),
      after: z.string().optional(),
      before: z.string().optional(),
      order: orderSchema,
    },
    argNames: ["campaign_id", "limit", "after", "before", "order"],
    handler: listAdGroups,
  },
  {
    name: "get_ad_group",
    description: "Get one ad group by id.",
    inputSchema: { ad_group_id: z.string() },
    argNames: ["ad_group_id"],
    handler: getAdGroup,
  },
  {
    name: "create_ad_group",
    description: "Create a paused ad group under a campaign with bid config and optional context hints.",
    inputSchema: {
      campaign_id: z.string(),
      name: z.string(),
      billing_event: z.enum(["impression", "click"]),
      max_bid_usd: z.number(),
      status: z.enum(["paused", "active"]).default("paused"),
      context_hints: z.any().optional(),
    },
    argNames: ["campaign_id", "name", "billing_event", "max_bid_usd", "status", "context_hints"],
    writes: true,
    handler: createAdGroup,
  },
  {
    name: "update_ad_group",
    description: "Update ad group fields, including bid config and context hints.",
    inputSchema: {
      ad_group_id: z.string(),
      name: z.string().optional(),
      billing_event: z.enum(["impression", "click"]).optional(),
      max_bid_usd: z.number().optional(),
      status: z.enum(["active", "paused", "archived"]).optional(),
      context_hints: z.any().optional(),
    },
    argNames: ["ad_group_id", "name", "billing_event", "max_bid_usd", "status", "context_hints"],
    writes: true,
    handler: updateAdGroup,
  },
  {
    name: "set_ad_group_state",
    description: "Activate, pause, or archive an ad group. Activation can start delivery when parent and child layers are active.",
    inputSchema: { ad_group_id: z.string(), state: z.enum(["activate", "pause", "archive"]) },
    argNames: ["ad_group_id", "state"],
    writes: true,
    destructive: true,
    openWorld: true,
    handler: setAdGroupState,
  },
];

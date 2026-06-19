import { z } from "zod";

import {
  badRequest,
  budgetGuard,
  coerceList,
  getClientOrError,
  handleApiError,
  isRecord,
  ok,
  optionalParams,
  usdToMicros,
  validateIntRange,
  validateNonEmpty,
  validateOption,
  validateUnixTime,
  type AdsToolDefinition,
  type JsonRecord,
  type ToolArgs,
} from "../core.js";

const CAMPAIGN_STATES = new Set(["activate", "pause", "archive"]);
const CAMPAIGN_STATUSES = new Set(["active", "paused", "archived"]);

export function locationsPayload(locations: unknown): [JsonRecord | null, string | null] {
  if (locations === undefined || locations === null) return [null, null];
  const [entries, error] = coerceList(locations, "locations");
  if (error) return [null, error];
  const include: JsonRecord[] = [];
  for (const entry of entries ?? []) {
    if (typeof entry === "string") {
      include.push({ id: entry });
    } else if (isRecord(entry)) {
      if (!entry.id) return [null, badRequest("Each location object must include id.")];
      include.push(entry);
    } else {
      return [null, badRequest("locations must contain location ids or objects.")];
    }
  }
  return [{ locations: { include } }, null];
}

export function buildCampaignBody(input: {
  name?: unknown;
  budget_usd?: unknown;
  status?: string;
  description?: unknown;
  start_time?: unknown;
  end_time?: unknown;
  mode?: string;
  locations?: unknown;
  confirm_budget?: unknown;
  create?: boolean;
}): [JsonRecord | null, string | null] {
  const body: JsonRecord = {};
  const create = input.create === true;
  if (input.name !== undefined && input.name !== null) {
    const error = validateNonEmpty("name", input.name, 3, 1000);
    if (error) return [null, error];
    body.name = String(input.name).trim();
  } else if (create) {
    return [null, badRequest("name is required.")];
  }
  const status = input.status ?? (create ? "paused" : undefined);
  if (status !== undefined) {
    if (!CAMPAIGN_STATUSES.has(status)) return [null, badRequest("status must be active, paused, or archived.")];
    if (create && status !== "paused") {
      return [null, badRequest("Create tools only create paused campaigns. Use set_campaign_state after review.")];
    }
    body.status = status;
  }
  if (input.budget_usd !== undefined && input.budget_usd !== null) {
    const budgetUsd = Number(input.budget_usd);
    const error = budgetGuard(budgetUsd, input.confirm_budget === true);
    if (error) return [null, error];
    body.budget = { lifetime_spend_limit_micros: usdToMicros(budgetUsd) };
  } else if (create) {
    return [null, badRequest("budget_usd is required.")];
  }
  if (input.description !== undefined) body.description = input.description;
  const startError = validateUnixTime("start_time", input.start_time);
  if (startError) return [null, startError];
  const endError = validateUnixTime("end_time", input.end_time);
  if (endError) return [null, endError];
  if (input.start_time !== undefined && input.start_time !== null) body.start_time = Number(input.start_time);
  if (input.end_time !== undefined && input.end_time !== null) body.end_time = Number(input.end_time);
  if (body.start_time !== undefined && body.end_time !== undefined && Number(body.end_time) <= Number(body.start_time)) {
    return [null, badRequest("end_time must be after start_time.")];
  }
  if (input.mode !== undefined && input.mode !== null) {
    if (input.mode !== "product_feed") return [null, badRequest("mode must be product_feed when provided.")];
    body.mode = input.mode;
  }
  const [targeting, targetingError] = locationsPayload(input.locations);
  if (targetingError) return [null, targetingError];
  if (targeting) body.targeting = targeting;
  if (!Object.keys(body).length) return [null, badRequest("Provide at least one field to update.")];
  return [body, null];
}

async function listCampaigns(args: ToolArgs): Promise<string> {
  const limit = Number(args.limit ?? 20);
  const limitError = validateIntRange("limit", limit, 1, 500);
  if (limitError) return limitError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get("/campaigns", optionalParams({ limit, after: args.after, before: args.before, order: args.order ?? "desc" })));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function getCampaign(args: ToolArgs): Promise<string> {
  const error = validateNonEmpty("campaign_id", args.campaign_id);
  if (error) return error;
  const { client, error: clientError } = getClientOrError();
  if (clientError) return clientError;
  try {
    return ok(await client!.get(`/campaigns/${args.campaign_id}`));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function createCampaign(args: ToolArgs): Promise<string> {
  const [body, bodyError] = buildCampaignBody({ ...args, status: String(args.status ?? "paused"), create: true });
  if (bodyError) return bodyError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post("/campaigns", body!));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function updateCampaign(args: ToolArgs): Promise<string> {
  const campaignError = validateNonEmpty("campaign_id", args.campaign_id);
  if (campaignError) return campaignError;
  const [body, bodyError] = buildCampaignBody(args);
  if (bodyError) return bodyError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post(`/campaigns/${args.campaign_id}`, body!));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function setCampaignState(args: ToolArgs): Promise<string> {
  const campaignError = validateNonEmpty("campaign_id", args.campaign_id);
  if (campaignError) return campaignError;
  const state = String(args.state);
  const stateError = validateOption("state", state, CAMPAIGN_STATES);
  if (stateError) return stateError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post(`/campaigns/${args.campaign_id}/${state}`));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

const orderSchema = z.enum(["asc", "desc"]).default("desc");
const campaignStatusSchema = z.enum(["paused", "active"]).default("paused");
const updateCampaignStatusSchema = z.enum(["active", "paused", "archived"]).optional();

export const campaignTools: AdsToolDefinition[] = [
  {
    name: "list_campaigns",
    description: "List campaigns in the authenticated ad account with cursor pagination.",
    inputSchema: {
      limit: z.number().int().default(20),
      after: z.string().optional(),
      before: z.string().optional(),
      order: orderSchema,
    },
    argNames: ["limit", "after", "before", "order"],
    handler: listCampaigns,
  },
  {
    name: "get_campaign",
    description: "Get one campaign by id.",
    inputSchema: { campaign_id: z.string() },
    argNames: ["campaign_id"],
    handler: getCampaign,
  },
  {
    name: "create_campaign",
    description: "Create an OpenAI Ads campaign, safely paused by default, with a guarded lifetime budget.",
    inputSchema: {
      name: z.string(),
      budget_usd: z.number(),
      status: campaignStatusSchema,
      description: z.string().optional(),
      start_time: z.number().int().optional(),
      end_time: z.number().int().optional(),
      mode: z.enum(["product_feed"]).optional(),
      locations: z.any().optional(),
      confirm_budget: z.boolean().default(false),
    },
    argNames: ["name", "budget_usd", "status", "description", "start_time", "end_time", "mode", "locations", "confirm_budget"],
    writes: true,
    destructive: true,
    openWorld: true,
    handler: createCampaign,
  },
  {
    name: "update_campaign",
    description: "Update campaign fields. Budget changes use the same ceiling guard as create_campaign.",
    inputSchema: {
      campaign_id: z.string(),
      name: z.string().optional(),
      budget_usd: z.number().optional(),
      status: updateCampaignStatusSchema,
      description: z.string().optional(),
      start_time: z.number().int().optional(),
      end_time: z.number().int().optional(),
      mode: z.enum(["product_feed"]).optional(),
      locations: z.any().optional(),
      confirm_budget: z.boolean().default(false),
    },
    argNames: ["campaign_id", "name", "budget_usd", "status", "description", "start_time", "end_time", "mode", "locations", "confirm_budget"],
    writes: true,
    destructive: true,
    openWorld: true,
    handler: updateCampaign,
  },
  {
    name: "set_campaign_state",
    description: "Activate, pause, or archive a campaign. Activation can start real spend when child layers are active.",
    inputSchema: { campaign_id: z.string(), state: z.enum(["activate", "pause", "archive"]) },
    argNames: ["campaign_id", "state"],
    writes: true,
    destructive: true,
    openWorld: true,
    handler: setCampaignState,
  },
];

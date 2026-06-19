import { existsSync } from "node:fs";
import { z } from "zod";

import {
  badRequest,
  getClientOrError,
  handleApiError,
  ok,
  optionalParams,
  validateIntRange,
  validateNonEmpty,
  validateOption,
  type AdsToolDefinition,
  type JsonRecord,
  type ToolArgs,
} from "../core.js";

const AD_STATES = new Set(["activate", "pause", "archive"]);
const AD_STATUSES = new Set(["active", "paused", "archived"]);
const CREATIVE_TYPES = new Set(["chat_card", "product_ad_template"]);

export function buildCreative(input: {
  creative_type?: unknown;
  title?: unknown;
  body?: unknown;
  target_url?: unknown;
  file_id?: unknown;
  price?: unknown;
  create?: boolean;
}): [JsonRecord | null, string | null] {
  const hasAny = ["creative_type", "title", "body", "target_url", "file_id", "price"].some((key) => input[key as keyof typeof input] !== undefined);
  if (!hasAny) return input.create ? [null, badRequest("creative_type, title, and body are required.")] : [null, null];
  const creativeType = String(input.creative_type);
  if (!CREATIVE_TYPES.has(creativeType)) return [null, badRequest("creative_type must be chat_card or product_ad_template.")];
  const titleError = validateNonEmpty("title", input.title, 3, 50);
  if (titleError) return [null, titleError];
  if (typeof input.body !== "string") return [null, badRequest("body is required.")];
  if (input.body.length > 100) return [null, badRequest("body must be at most 100 characters.")];
  const creative: JsonRecord = { type: creativeType, title: input.title, body: input.body };
  if (creativeType === "chat_card") {
    const targetError = validateNonEmpty("target_url", input.target_url, 1, 2048);
    if (targetError) return [null, targetError];
    const fileError = validateNonEmpty("file_id", input.file_id);
    if (fileError) return [null, fileError];
    creative.target_url = input.target_url;
    creative.file_id = input.file_id;
  }
  if (input.price !== undefined && input.price !== null) {
    if (String(input.price).length > 100) return [null, badRequest("price must be at most 100 characters.")];
    creative.price = input.price;
  }
  return [creative, null];
}

export function buildAdBody(input: {
  ad_group_id?: unknown;
  name?: unknown;
  creative_type?: unknown;
  title?: unknown;
  body?: unknown;
  target_url?: unknown;
  file_id?: unknown;
  price?: unknown;
  status?: string;
  create?: boolean;
}): [JsonRecord | null, string | null] {
  const payload: JsonRecord = {};
  const create = input.create === true;
  if (create) {
    const adGroupError = validateNonEmpty("ad_group_id", input.ad_group_id);
    if (adGroupError) return [null, adGroupError];
    payload.ad_group_id = input.ad_group_id;
  }
  if (input.name !== undefined && input.name !== null) {
    const nameError = validateNonEmpty("name", input.name, 3, 1000);
    if (nameError) return [null, nameError];
    payload.name = String(input.name).trim();
  } else if (create) {
    return [null, badRequest("name is required.")];
  }
  const [creative, creativeError] = buildCreative(input);
  if (creativeError) return [null, creativeError];
  if (creative) payload.creative = creative;
  const status = input.status ?? (create ? "paused" : undefined);
  if (status !== undefined) {
    if (!AD_STATUSES.has(status)) return [null, badRequest("status must be active, paused, or archived.")];
    if (create && status !== "paused") return [null, badRequest("Create tools only create paused ads. Use set_ad_state after review.")];
    payload.status = status;
  }
  if (!Object.keys(payload).length) return [null, badRequest("Provide at least one field to update.")];
  return [payload, null];
}

async function listAds(args: ToolArgs): Promise<string> {
  const adGroupError = validateNonEmpty("ad_group_id", args.ad_group_id);
  if (adGroupError) return adGroupError;
  const limit = Number(args.limit ?? 20);
  const limitError = validateIntRange("limit", limit, 1, 500);
  if (limitError) return limitError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get("/ads", optionalParams({ ad_group_id: args.ad_group_id, limit, after: args.after, before: args.before, order: args.order ?? "desc" })));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function getAd(args: ToolArgs): Promise<string> {
  const adError = validateNonEmpty("ad_id", args.ad_id);
  if (adError) return adError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get(`/ads/${args.ad_id}`));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function uploadCreative(args: ToolArgs): Promise<string> {
  if (Boolean(args.image_url) === Boolean(args.file_path)) return badRequest("Provide exactly one of image_url or file_path.");
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    if (args.image_url) return ok(await client!.post("/upload", { image_url: args.image_url }));
    const filePath = String(args.file_path);
    if (!existsSync(filePath)) return badRequest("file_path must point to an existing file.");
    return ok(await client!.uploadFile("/upload", filePath));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function createAd(args: ToolArgs): Promise<string> {
  const [payload, payloadError] = buildAdBody({ ...args, status: String(args.status ?? "paused"), create: true });
  if (payloadError) return payloadError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post("/ads", payload!));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function updateAd(args: ToolArgs): Promise<string> {
  const adError = validateNonEmpty("ad_id", args.ad_id);
  if (adError) return adError;
  const [payload, payloadError] = buildAdBody(args);
  if (payloadError) return payloadError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post(`/ads/${args.ad_id}`, payload!));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function setAdState(args: ToolArgs): Promise<string> {
  const adError = validateNonEmpty("ad_id", args.ad_id);
  if (adError) return adError;
  const state = String(args.state);
  const stateError = validateOption("state", state, AD_STATES);
  if (stateError) return stateError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.post(`/ads/${args.ad_id}/${state}`));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

const orderSchema = z.enum(["asc", "desc"]).default("desc");
const creativeTypeSchema = z.enum(["chat_card", "product_ad_template"]);

export const adTools: AdsToolDefinition[] = [
  {
    name: "list_ads",
    description: "List ads in an ad group.",
    inputSchema: { ad_group_id: z.string(), limit: z.number().int().default(20), after: z.string().optional(), before: z.string().optional(), order: orderSchema },
    argNames: ["ad_group_id", "limit", "after", "before", "order"],
    handler: listAds,
  },
  {
    name: "get_ad",
    description: "Get one ad by id, including review_status and creative metadata.",
    inputSchema: { ad_id: z.string() },
    argNames: ["ad_id"],
    handler: getAd,
  },
  {
    name: "upload_creative",
    description: "Upload a creative image by image_url or local file_path and receive a file_id.",
    inputSchema: { image_url: z.string().optional(), file_path: z.string().optional() },
    argNames: ["image_url", "file_path"],
    writes: true,
    handler: uploadCreative,
  },
  {
    name: "create_ad",
    description: "Create a paused ad. chat_card creatives require target_url and file_id.",
    inputSchema: {
      ad_group_id: z.string(),
      name: z.string(),
      creative_type: creativeTypeSchema,
      title: z.string(),
      body: z.string(),
      target_url: z.string().optional(),
      file_id: z.string().optional(),
      price: z.string().optional(),
      status: z.enum(["paused", "active"]).default("paused"),
    },
    argNames: ["ad_group_id", "name", "creative_type", "title", "body", "target_url", "file_id", "price", "status"],
    writes: true,
    handler: createAd,
  },
  {
    name: "update_ad",
    description: "Update ad name, creative, or status.",
    inputSchema: {
      ad_id: z.string(),
      name: z.string().optional(),
      creative_type: creativeTypeSchema.optional(),
      title: z.string().optional(),
      body: z.string().optional(),
      target_url: z.string().optional(),
      file_id: z.string().optional(),
      price: z.string().optional(),
      status: z.enum(["active", "paused", "archived"]).optional(),
    },
    argNames: ["ad_id", "name", "creative_type", "title", "body", "target_url", "file_id", "price", "status"],
    writes: true,
    handler: updateAd,
  },
  {
    name: "set_ad_state",
    description: "Activate, pause, or archive an ad. Activation can start real delivery once parent layers are active.",
    inputSchema: { ad_id: z.string(), state: z.enum(["activate", "pause", "archive"]) },
    argNames: ["ad_id", "state"],
    writes: true,
    destructive: true,
    openWorld: true,
    handler: setAdState,
  },
];

import { z } from "zod";

import {
  badRequest,
  coerceList,
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

async function listAudiences(args: ToolArgs): Promise<string> {
  const limit = Number(args.limit ?? 20);
  const limitError = validateIntRange("limit", limit, 1, 500);
  if (limitError) return limitError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get("/custom_audiences", optionalParams({ limit, after: args.after, before: args.before, order: args.order ?? "desc" })));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function getAudience(args: ToolArgs): Promise<string> {
  const audienceError = validateNonEmpty("audience_id", args.audience_id);
  if (audienceError) return audienceError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get(`/custom_audiences/${args.audience_id}`));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

async function searchGeo(args: ToolArgs): Promise<string> {
  const queryError = validateNonEmpty("query", args.query, 1, 200);
  if (queryError) return queryError;
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get("/geo_lookup/search", { q: args.query, limit: 20 }));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

function membersPayload(members: unknown): [JsonRecord[] | null, string | null] {
  const [memberList, error] = coerceList(members, "members");
  if (error) return [null, error];
  if (!memberList?.length) return [null, badRequest("members is required for action='create'.")];
  const out: JsonRecord[] = [];
  for (const member of memberList) {
    if (!isRecord(member)) return [null, badRequest("Each audience member must be an object.")];
    if (!["email", "phone", "email_sha256", "phone_number_sha256"].includes(String(member.identifier_type))) {
      return [null, badRequest("member identifier_type must be email, phone, email_sha256, or phone_number_sha256.")];
    }
    if (typeof member.value !== "string" || !member.value) return [null, badRequest("Each audience member must include a non-empty value.")];
    out.push({ identifier_type: member.identifier_type, value: member.value });
  }
  return [out, null];
}

async function manageAudience(args: ToolArgs): Promise<string> {
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    if (args.action === "create") {
      const nameError = validateNonEmpty("name", args.name, 3, 1000);
      if (nameError) return nameError;
      const [members, membersError] = membersPayload(args.members);
      if (membersError) return membersError;
      const body: JsonRecord = { name: args.name, members };
      if (args.description) body.description = args.description;
      return ok(await client!.post("/custom_audiences", body));
    }
    if (args.action === "upload") {
      const nameError = validateNonEmpty("name", args.name, 3, 1000);
      if (nameError) return nameError;
      for (const fieldName of ["file_id", "filename", "mimetype"]) {
        const fieldError = validateNonEmpty(fieldName, args[fieldName]);
        if (fieldError) return fieldError;
      }
      const fileSize = Number(args.file_size);
      if (!fileSize || fileSize < 1) return badRequest("file_size must be at least 1.");
      const body: JsonRecord = {
        name: args.name,
        file_id: args.file_id,
        filename: args.filename,
        mimetype: args.mimetype,
        file_size: fileSize,
      };
      if (args.description) body.description = args.description;
      if (args.identifier_type) body.identifier_type = args.identifier_type;
      return ok(await client!.post("/custom_audiences/upload", body));
    }
    if (args.action === "archive") {
      const audienceError = validateNonEmpty("audience_id", args.audience_id);
      if (audienceError) return audienceError;
      return ok(await client!.post(`/custom_audiences/${args.audience_id}/archive`));
    }
    return badRequest(`Unknown action: ${String(args.action)}`);
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

const orderSchema = z.enum(["asc", "desc"]).default("desc");

export const audienceTools: AdsToolDefinition[] = [
  {
    name: "list_audiences",
    description: "List custom audiences for the authenticated ad account.",
    inputSchema: { limit: z.number().int().default(20), after: z.string().optional(), before: z.string().optional(), order: orderSchema },
    argNames: ["limit", "after", "before", "order"],
    handler: listAudiences,
  },
  {
    name: "get_audience",
    description: "Get one custom audience by id.",
    inputSchema: { audience_id: z.string() },
    argNames: ["audience_id"],
    handler: getAudience,
  },
  {
    name: "search_geo",
    description: "Search geo targets for targeting.locations.include and return ids usable in campaign targeting.",
    inputSchema: { query: z.string() },
    argNames: ["query"],
    handler: searchGeo,
  },
  {
    name: "manage_audience",
    description: "Create, upload, or archive a custom audience.",
    inputSchema: {
      action: z.enum(["create", "upload", "archive"]),
      name: z.string().optional(),
      description: z.string().optional(),
      members: z.any().optional(),
      audience_id: z.string().optional(),
      file_id: z.string().optional(),
      identifier_type: z.enum(["email", "phone", "email_sha256", "phone_number_sha256"]).optional(),
      filename: z.string().optional(),
      mimetype: z.string().optional(),
      file_size: z.number().int().optional(),
    },
    argNames: ["action", "name", "description", "members", "audience_id", "file_id", "identifier_type", "filename", "mimetype", "file_size"],
    writes: true,
    destructive: true,
    handler: manageAudience,
  },
];

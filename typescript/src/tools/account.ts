import { z } from "zod";

import { getClientOrError, handleApiError, ok, type AdsToolDefinition } from "../core.js";

export async function getAccount(): Promise<string> {
  const { client, error } = getClientOrError();
  if (error) return error;
  try {
    return ok(await client!.get("/ad_account"));
  } catch (apiError) {
    return handleApiError(apiError);
  }
}

export const accountTools: AdsToolDefinition[] = [
  {
    name: "get_account",
    description:
      "Get the authenticated OpenAI Ads account. Use this first to verify that OPENAI_ADS_API_KEY works and to read account id, name, timezone, currency, and settings.",
    inputSchema: {},
    argNames: [],
    handler: () => getAccount(),
  },
];

void z;

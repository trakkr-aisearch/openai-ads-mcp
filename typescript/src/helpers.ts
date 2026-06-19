import { z } from "zod";

import { OpenAIAdsAPIError } from "./client.js";
import {
  badRequest,
  coerceList,
  coerceMapping,
  coerceStringList,
  extractId,
  getClientOrError,
  handleApiError,
  isRecord,
  ok,
  validateNonEmpty,
  type AdsToolDefinition,
  type JsonRecord,
  type ToolArgs,
} from "./core.js";
import { buildAdGroupBody } from "./tools/adgroups.js";
import { buildAdBody } from "./tools/ads.js";
import { buildCampaignBody } from "./tools/campaigns.js";

function parseToolError(errorText: string): JsonRecord {
  try {
    const parsed = JSON.parse(errorText) as unknown;
    return isRecord(parsed) ? parsed : { message: errorText };
  } catch {
    return { message: errorText };
  }
}

async function buildCampaign(args: ToolArgs): Promise<string> {
  const [groupPayload, groupParseError] = coerceMapping(args.ad_group, "ad_group");
  if (groupParseError) return groupParseError;
  const [adPayloads, adsParseError] = coerceList(args.ads, "ads");
  if (adsParseError) return adsParseError;
  if (!adPayloads?.length) return badRequest("ads must include at least one ad.");
  const [campaignBody, campaignError] = buildCampaignBody({
    name: args.name,
    budget_usd: args.budget_usd,
    status: "paused",
    confirm_budget: args.confirm_budget,
    create: true,
  });
  if (campaignError) return campaignError;
  const { client, error } = getClientOrError();
  if (error) return error;
  const created: { campaign: JsonRecord | null; ad_group: JsonRecord | null; ads: JsonRecord[] } = {
    campaign: null,
    ad_group: null,
    ads: [],
  };
  try {
    const campaign = await client!.post("/campaigns", campaignBody!);
    created.campaign = campaign;
    const campaignId = extractId(campaign, "id", "campaign_id");
    if (!campaignId) {
      return ok({ created, error: { message: "Campaign was created but no id was returned." } });
    }
    const [adGroupBody, adGroupError] = buildAdGroupBody({
      campaign_id: campaignId,
      name: groupPayload?.name,
      billing_event: groupPayload?.billing_event as string | undefined,
      max_bid_usd: groupPayload?.max_bid_usd,
      status: "paused",
      context_hints: groupPayload?.context_hints,
      create: true,
    });
    if (adGroupError) {
      return ok({ created, error: parseToolError(adGroupError) });
    }
    const adGroup = await client!.post("/ad_groups", adGroupBody!);
    created.ad_group = adGroup;
    const adGroupId = extractId(adGroup, "id", "ad_group_id");
    if (!adGroupId) {
      return ok({ created, error: { message: "Ad group was created but no id was returned." } });
    }
    for (const [index, ad] of adPayloads.entries()) {
      if (!isRecord(ad)) {
        return ok({ created, error: { message: `ads[${index}] must be an object.` } });
      }
      const [adBody, adError] = buildAdBody({
        ad_group_id: adGroupId,
        name: ad.name ?? ad.title,
        creative_type: ad.creative_type ?? "chat_card",
        title: ad.title,
        body: ad.body,
        target_url: ad.target_url,
        file_id: ad.file_id,
        price: ad.price,
        status: "paused",
        create: true,
      });
      if (adError) {
        return ok({ created, error: parseToolError(adError) });
      }
      created.ads.push(await client!.post("/ads", adBody!));
    }
    return ok({
      created,
      note: "Created paused. To go live, call set_campaign_state/set_ad_group_state/set_ad_state with state='activate'.",
    });
  } catch (apiError) {
    if (apiError instanceof OpenAIAdsAPIError && (created.campaign || created.ad_group || created.ads.length)) {
      return ok({ created, error: { status_code: apiError.statusCode, message: apiError.detail } });
    }
    return handleApiError(apiError);
  }
}

async function draftContextHints(args: ToolArgs): Promise<string> {
  const productError = validateNonEmpty("product", args.product, 2, 200);
  if (productError) return productError;
  const [keywordValues, keywordsError] = coerceStringList(args.keywords, "keywords");
  if (keywordsError) return keywordsError;
  const product = String(args.product).trim();
  const audience = typeof args.audience === "string" && args.audience.trim() ? args.audience.trim() : null;
  const intent = typeof args.intent === "string" && args.intent.trim() ? args.intent.trim() : null;
  const bits = [`Product: ${product}`];
  if (audience) bits.push(`Audience: ${audience}`);
  if (intent) bits.push(`Intent: ${intent}`);
  if (keywordValues?.length) bits.push(`Keywords: ${keywordValues.slice(0, 12).join(", ")}`);
  const base = bits.join(" | ");
  const hints = [
    {
      context_hint: base,
      rationale: "Broad enough to capture the category, narrow enough to avoid unrelated prompts.",
    },
    {
      context_hint: `${base} | Moment: comparing options, reading recommendations, or asking what to buy`,
      rationale: "Targets high-intent discovery moments where paid placement can shape a shortlist.",
    },
  ];
  if (audience) {
    hints.push({
      context_hint: `Product: ${product} | Audience problem: ${audience} needs a credible solution`,
      rationale: "Frames the ad around the buyer and use case rather than only the product name.",
    });
  }
  return ok({ context_hints: hints.map((item) => item.context_hint), drafts: hints });
}

async function bulkAbTestHints(args: ToolArgs): Promise<string> {
  const adGroupError = validateNonEmpty("ad_group_id", args.ad_group_id);
  if (adGroupError) return adGroupError;
  const [parsed, variantsError] = coerceList(args.variants, "variants");
  if (variantsError) return variantsError;
  if (!parsed?.length) return badRequest("variants must include at least one variant.");
  if (parsed.length > 20) return badRequest("Create at most 20 variants per A/B test batch.");
  const { client, error } = getClientOrError();
  if (error) return error;
  const created: JsonRecord[] = [];
  try {
    for (const [index, variant] of parsed.entries()) {
      if (!isRecord(variant)) {
        return ok({ created, error: { message: `variants[${index}] must be an object.` } });
      }
      const [adBody, adError] = buildAdBody({
        ad_group_id: args.ad_group_id,
        name: variant.name ?? `AB test: ${String(variant.title ?? index + 1)}`,
        creative_type: variant.creative_type ?? "chat_card",
        title: variant.title,
        body: variant.body,
        target_url: variant.target_url,
        file_id: variant.file_id,
        price: variant.price,
        status: "paused",
        create: true,
      });
      if (adError) {
        return ok({ created, error: parseToolError(adError) });
      }
      created.push(await client!.post("/ads", adBody!));
    }
    return ok({
      created_ads: created,
      ad_ids: created.map((ad) => extractId(ad, "id", "ad_id")),
      note: "Created paused. Activate only the variants you are ready to test.",
    });
  } catch (apiError) {
    if (apiError instanceof OpenAIAdsAPIError) {
      return ok({ created, error: { status_code: apiError.statusCode, message: apiError.detail } });
    }
    return handleApiError(apiError);
  }
}

export const helperTools: AdsToolDefinition[] = [
  {
    name: "build_campaign",
    description: "Build one paused campaign tree with one ad group and multiple paused ads, with guarded budget handling.",
    inputSchema: {
      name: z.string(),
      budget_usd: z.number(),
      ad_group: z.any(),
      ads: z.any(),
      confirm_budget: z.boolean().default(false),
    },
    argNames: ["name", "budget_usd", "ad_group", "ads", "confirm_budget"],
    writes: true,
    destructive: true,
    openWorld: true,
    handler: buildCampaign,
  },
  {
    name: "draft_context_hints",
    description: "Draft deterministic context_hints for an ad group from product, audience, intent, and keywords.",
    inputSchema: {
      product: z.string(),
      audience: z.string().optional(),
      intent: z.string().optional(),
      keywords: z.any().optional(),
    },
    argNames: ["product", "audience", "intent", "keywords"],
    handler: draftContextHints,
  },
  {
    name: "bulk_ab_test_hints",
    description: "Create multiple paused chat_card ad variants under one ad group for a clean A/B test.",
    inputSchema: {
      ad_group_id: z.string(),
      variants: z.any(),
    },
    argNames: ["ad_group_id", "variants"],
    writes: true,
    handler: bulkAbTestHints,
  },
];

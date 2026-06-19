"""Opinionated helper tools for safer OpenAI Ads workflows."""

from __future__ import annotations

from ._core import *
from .tools_adgroups import _build_ad_group_body
from .tools_ads import _build_ad_body
from .tools_campaigns import _build_campaign_body


@ads_tool(writes=True, destructive=True, open_world=True)
async def build_campaign(
    name: str,
    budget_usd: float,
    ad_group: Any,
    ads: Any,
    confirm_budget: bool = False,
) -> str:
    """Build a complete paused campaign tree in one guarded workflow.

    Creates one campaign, one ad group, and N ads. Everything is created paused.
    If a step fails, the response includes whatever was created so far plus the
    error so you can clean up or continue deliberately.

    ad_group must be an object with name, billing_event, and max_bid_usd. It may
    include context_hints. ads must be a list of objects accepted by create_ad:
    name, creative_type, title, body, target_url, file_id, and optional price.
    """
    group_payload, group_parse_err = _coerce_mapping(ad_group, "ad_group")
    if group_parse_err:
        return group_parse_err
    ad_payloads, ads_parse_err = _coerce_list(ads, "ads")
    if ads_parse_err:
        return ads_parse_err
    if not ad_payloads:
        return _bad_request("ads must include at least one ad.")
    campaign_body, campaign_err = _build_campaign_body(
        name=name,
        budget_usd=budget_usd,
        status="paused",
        confirm_budget=confirm_budget,
        create=True,
    )
    if campaign_err:
        return campaign_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    created: dict[str, Any] = {"campaign": None, "ad_group": None, "ads": []}
    try:
        campaign = await client.post("/campaigns", json=campaign_body)
        created["campaign"] = campaign
        campaign_id = _extract_id(campaign, "id", "campaign_id")
        if not campaign_id:
            return _ok({"created": created, "error": {"message": "Campaign was created but no id was returned."}})
        ad_group_body, ad_group_err = _build_ad_group_body(
            campaign_id=campaign_id,
            name=group_payload.get("name"),
            billing_event=group_payload.get("billing_event"),
            max_bid_usd=group_payload.get("max_bid_usd"),
            status="paused",
            context_hints=group_payload.get("context_hints"),
            create=True,
        )
        if ad_group_err:
            return _ok({"created": created, "error": json.loads(ad_group_err)})
        group = await client.post("/ad_groups", json=ad_group_body)
        created["ad_group"] = group
        ad_group_id = _extract_id(group, "id", "ad_group_id")
        if not ad_group_id:
            return _ok({"created": created, "error": {"message": "Ad group was created but no id was returned."}})
        for index, ad in enumerate(ad_payloads):
            if not isinstance(ad, dict):
                return _ok({"created": created, "error": {"message": f"ads[{index}] must be an object."}})
            ad_body, ad_err = _build_ad_body(
                ad_group_id=ad_group_id,
                name=ad.get("name") or ad.get("title"),
                creative_type=ad.get("creative_type", "chat_card"),
                title=ad.get("title"),
                body=ad.get("body"),
                target_url=ad.get("target_url"),
                file_id=ad.get("file_id"),
                price=ad.get("price"),
                status="paused",
                create=True,
            )
            if ad_err:
                return _ok({"created": created, "error": json.loads(ad_err)})
            created_ad = await client.post("/ads", json=ad_body)
            created["ads"].append(created_ad)
        return _ok({
            "created": created,
            "note": "Created paused. To go live, call set_campaign_state/set_ad_group_state/set_ad_state with state='activate'.",
        })
    except OpenAIAdsAPIError as e:
        if created["campaign"] or created["ad_group"] or created["ads"]:
            return _ok({"created": created, "error": {"status_code": e.status_code, "message": e.detail}})
        return _err(e)


@ads_tool()
async def draft_context_hints(
    product: str,
    audience: str | None = None,
    intent: str | None = None,
    keywords: Any = None,
) -> str:
    """Draft deterministic context_hints for an ad group.

    No external model call is made. The output is shaped for the OpenAI Ads API:
    context_hints is a list of strings that can be passed directly to
    create_ad_group or update_ad_group.
    """
    if product_err := _validate_non_empty("product", product, minimum=2, maximum=200):
        return product_err
    keyword_values, keywords_err = _coerce_string_list(keywords, "keywords")
    if keywords_err:
        return keywords_err
    bits = [f"Product: {product.strip()}"]
    if audience:
        bits.append(f"Audience: {audience.strip()}")
    if intent:
        bits.append(f"Intent: {intent.strip()}")
    if keyword_values:
        bits.append("Keywords: " + ", ".join(keyword_values[:12]))
    base = " | ".join(bits)
    hints = [
        {
            "context_hint": base,
            "rationale": "Broad enough to capture the category, narrow enough to avoid unrelated prompts.",
        },
        {
            "context_hint": base + " | Moment: comparing options, reading recommendations, or asking what to buy",
            "rationale": "Targets high-intent discovery moments where paid placement can shape a shortlist.",
        },
    ]
    if audience:
        hints.append({
            "context_hint": f"Product: {product.strip()} | Audience problem: {audience.strip()} needs a credible solution",
            "rationale": "Frames the ad around the buyer and use case rather than only the product name.",
        })
    return _ok({"context_hints": [item["context_hint"] for item in hints], "drafts": hints})


@ads_tool(writes=True)
async def bulk_ab_test_hints(ad_group_id: str, variants: Any) -> str:
    """Create multiple paused chat_card ads under one ad group for a clean A/B test.

    variants is a list of objects with title, body, target_url, file_id, and
    optional name or price. Every created ad is paused.
    """
    if ad_group_err := _validate_non_empty("ad_group_id", ad_group_id):
        return ad_group_err
    parsed, variants_err = _coerce_list(variants, "variants")
    if variants_err:
        return variants_err
    if not parsed:
        return _bad_request("variants must include at least one variant.")
    if len(parsed) > 20:
        return _bad_request("Create at most 20 variants per A/B test batch.")
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    created: list[dict[str, Any]] = []
    try:
        for index, variant in enumerate(parsed):
            if not isinstance(variant, dict):
                return _ok({"created": created, "error": {"message": f"variants[{index}] must be an object."}})
            ad_body, ad_err = _build_ad_body(
                ad_group_id=ad_group_id,
                name=variant.get("name") or f"AB test: {variant.get('title', index + 1)}",
                creative_type=variant.get("creative_type", "chat_card"),
                title=variant.get("title"),
                body=variant.get("body"),
                target_url=variant.get("target_url"),
                file_id=variant.get("file_id"),
                price=variant.get("price"),
                status="paused",
                create=True,
            )
            if ad_err:
                return _ok({"created": created, "error": json.loads(ad_err)})
            ad = await client.post("/ads", json=ad_body)
            created.append(ad)
        return _ok({
            "created_ads": created,
            "ad_ids": [_extract_id(ad, "id", "ad_id") for ad in created],
            "note": "Created paused. Activate only the variants you are ready to test.",
        })
    except OpenAIAdsAPIError as e:
        return _ok({"created": created, "error": {"status_code": e.status_code, "message": e.detail}})


__all__ = ("build_campaign", "draft_context_hints", "bulk_ab_test_hints")

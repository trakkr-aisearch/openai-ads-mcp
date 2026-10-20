"""Opinionated helper tools for safer OpenAI Ads workflows."""

from __future__ import annotations

from ._core import *
from .tools_adgroups import _build_ad_group_body
from .tools_ads import _build_ad_body, _image_source, _upload_image
from .tools_campaigns import _build_campaign_body


_PENDING_ID = "pending"


@ads_tool(writes=True, destructive=True, open_world=True)
async def build_campaign(
    name: str,
    ad_group: Any,
    ads: Any,
    lifetime_budget: float | None = None,
    daily_budget: float | None = None,
    description: str | None = None,
    bidding_type: Literal["impressions", "clicks", "conversions"] | None = None,
    conversion_event_setting_id: str | None = None,
    confirm_budget: bool = False,
    confirm_bid: bool = False,
    idempotency_key: str | None = None,
    budget_usd: float | None = None,
) -> str:
    """Build a complete campaign tree in one guarded workflow.

    Creates one campaign, one ad group, and N ads. The campaign is created paused; its ad group
    and ads are created active under it, so nothing serves until the campaign is activated with
    set_campaign_state, and that one step takes the whole tree live.
    Every body is validated before the first request; if an API call fails, the
    response includes whatever was created so far plus the error so you can
    clean up or continue deliberately.

    lifetime_budget or daily_budget (one, not both) is the campaign's spend
    limit in the ad account's currency, major units (500 = ₹500 or $500; call
    get_account to see the currency). A lifetime_budget above
    OPENAI_ADS_BUDGET_CEILING, or any daily_budget (it has no end_time here),
    needs confirm_budget=True. description is the campaign's.

    ad_group must be an object with name and billing_event, plus max_bid
    (account currency, major units; above OPENAI_ADS_BID_CEILING needs
    confirm_bid=True) unless bidding_strategy is maximize_clicks or
    maximize_conversions. It may include description, bidding_strategy,
    custom_audience_bid_multipliers, context_hints, and product_set. ads must be
    a list of objects accepted by create_ad: name, creative_type, title, body,
    target_url, one image (file_id; image_url, a public https image; or
    image_base64 + image_filename, the image bytes — an upload happens only after
    every body validates and before anything is created), and optional price.
    budget_usd was renamed to
    lifetime_budget and is refused.
    """
    if renamed_err := _reject_renamed(budget_usd=budget_usd):
        return renamed_err
    group_payload, group_parse_err = _coerce_mapping(ad_group, "ad_group")
    if group_parse_err:
        return group_parse_err
    if renamed_err := _reject_renamed(max_bid_usd=group_payload.get("max_bid_usd")):
        return renamed_err
    ad_payloads, ads_parse_err = _coerce_list(ads, "ads")
    if ads_parse_err:
        return ads_parse_err
    if not ad_payloads:
        return _bad_request("ads must include at least one ad.")
    idempotency_key, idempotency_err = _validate_idempotency_key(idempotency_key)
    if idempotency_err:
        return idempotency_err
    has_product_set = group_payload.get("product_set") is not None
    if bidding_type == "conversions" and group_payload.get("billing_event") != "click":
        return _bad_request(
            "Conversion-optimized campaign ad groups must use billing_event='click'. "
            "The bid is your CPA input even though billing remains per click."
        )
    campaign_body, campaign_err = _build_campaign_body(
        name=name,
        lifetime_budget=lifetime_budget,
        daily_budget=daily_budget,
        description=description,
        status="paused",
        mode="product_feed" if has_product_set else None,
        bidding_type=bidding_type,
        conversion_event_setting_ids=[conversion_event_setting_id] if conversion_event_setting_id else None,
        confirm_budget=confirm_budget,
        create=True,
    )
    if campaign_err:
        return campaign_err
    # Parent ids are unknown until each POST returns, so validate with a placeholder and fill it in later.
    ad_group_body, ad_group_err = _build_ad_group_body(
        campaign_id=_PENDING_ID,
        name=group_payload.get("name"),
        description=group_payload.get("description"),
        billing_event=group_payload.get("billing_event"),
        max_bid=group_payload.get("max_bid"),
        bidding_strategy=group_payload.get("bidding_strategy"),
        custom_audience_bid_multipliers=group_payload.get("custom_audience_bid_multipliers"),
        status="paused",
        context_hints=group_payload.get("context_hints"),
        product_set=group_payload.get("product_set"),
        confirm_bid=confirm_bid,
        create=True,
    )
    if ad_group_err:
        return ad_group_err
    ad_bodies = []
    image_uploads = []
    for index, ad in enumerate(ad_payloads):
        if not isinstance(ad, dict):
            return _bad_request(f"ads[{index}] must be an object.")
        file_id, image_upload, image_err = _image_source(
            ad.get("file_id"), ad.get("image_url"), ad.get("image_base64"), ad.get("image_filename")
        )
        if image_err:
            return _bad_request(f"ads[{index}]: {json.loads(image_err)['message']}")
        ad_body, ad_err = _build_ad_body(
            ad_group_id=_PENDING_ID,
            name=ad.get("name") or ad.get("title"),
            creative_type=ad.get("creative_type", "chat_card"),
            title=ad.get("title"),
            body=ad.get("body"),
            target_url=ad.get("target_url"),
            file_id=file_id,
            price=ad.get("price"),
            status="paused",
            create=True,
        )
        if ad_err:
            return _bad_request(f"ads[{index}]: {json.loads(ad_err)['message']}")
        # Children ready under a paused campaign (OpenAI accepts this; checked 2026-10-20): nothing
        # serves until the campaign is activated, and that single step takes the tree live.
        ad_body["status"] = "active"
        ad_bodies.append(ad_body)
        image_uploads.append(image_upload)
    ad_group_body["status"] = "active"
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    created: dict[str, Any] = {"campaign": None, "ad_group": None, "ads": []}
    try:
        # Images first: an upload that fails leaves nothing created.
        for index, image_upload in enumerate(image_uploads):
            if image_upload:
                uploaded = await _upload_image(client, image_upload)
                if not uploaded:
                    return _bad_request(f"ads[{index}]: the image upload returned no file_id; nothing was created.")
                ad_bodies[index]["creative"]["file_id"] = uploaded
        campaign = await client.post(
            "/campaigns", json=campaign_body, idempotency_key=_child_idempotency_key(idempotency_key, "campaign")
        )
        created["campaign"] = campaign
        campaign_id = _extract_id(campaign, "id", "campaign_id")
        if not campaign_id:
            return _ok({"created": created, "error": {"message": "Campaign was created but no id was returned."}})
        ad_group_body["campaign_id"] = campaign_id
        group = await client.post(
            "/ad_groups", json=ad_group_body, idempotency_key=_child_idempotency_key(idempotency_key, "ad_group")
        )
        created["ad_group"] = group
        ad_group_id = _extract_id(group, "id", "ad_group_id")
        if not ad_group_id:
            return _ok({"created": created, "error": {"message": "Ad group was created but no id was returned."}})
        for index, ad_body in enumerate(ad_bodies):
            ad_body["ad_group_id"] = ad_group_id
            created_ad = await client.post(
                "/ads", json=ad_body, idempotency_key=_child_idempotency_key(idempotency_key, f"ad_{index}")
            )
            created["ads"].append(created_ad)
        return _ok({
            "created": created,
            "note": "Campaign created paused; its ad group and ads are ready. To go live, activate the campaign with set_campaign_state state='activate'.",
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


@ads_tool(writes=True, open_world=True)
async def bulk_ab_test_hints(ad_group_id: str, variants: Any, idempotency_key: str | None = None) -> str:
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
    idempotency_key, idempotency_err = _validate_idempotency_key(idempotency_key)
    if idempotency_err:
        return idempotency_err
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
            ad_kwargs = {"json": ad_body}
            ad_key = _child_idempotency_key(idempotency_key, f"ad_{index}")
            if ad_key:
                ad_kwargs["idempotency_key"] = ad_key
            ad = await client.post("/ads", **ad_kwargs)
            created.append(ad)
        return _ok({
            "created_ads": created,
            "ad_ids": [_extract_id(ad, "id", "ad_id") for ad in created],
            "note": "Created paused. Activate only the variants you are ready to test.",
        })
    except OpenAIAdsAPIError as e:
        return _ok({"created": created, "error": {"status_code": e.status_code, "message": e.detail}})


__all__ = ("build_campaign", "draft_context_hints", "bulk_ab_test_hints")

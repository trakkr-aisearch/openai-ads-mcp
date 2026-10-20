"""Ad group MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *

_AD_GROUP_STATES = {"activate", "pause", "archive"}
_AD_GROUP_STATUSES = {"active", "paused", "archived"}
_BILLING_EVENTS = {"impression", "click"}
_BIDDING_STRATEGIES = {"fixed_bid", "maximize_clicks", "maximize_conversions"}
# The spec's BiddingConfigParams.max_bid_micros maximum (30.4e12 micros), in major units of the account currency.
# The everyday limit is OPENAI_ADS_BID_CEILING (confirm_bid); this is only the API's hard cap.
_MAX_BID = 30_400_000
_PRODUCT_SET_FILTER_OPERATORS = {"in", "gt", "gte", "lt", "lte"}
_PRODUCT_SET_FILTER_FIELDS = {
    "title",
    "body",
    "item_id",
    "offer_id",
    "price",
    "target_url",
    "image_url",
    "product_category",
    "brand",
    "seller_name",
    "external_seller_id",
    "star_rating",
    "condition",
    "age_group",
}
_PRODUCT_SET_COMPARISON_FIELDS = {"price", "star_rating"}


def _product_set_payload(product_set: Any) -> tuple[dict[str, Any] | None, str | None]:
    if product_set is None:
        return None, None
    product_set, product_set_err = _coerce_mapping(product_set, "product_set")
    if product_set_err:
        return None, product_set_err
    if feed_err := _validate_non_empty("product_set.product_feed_id", product_set.get("product_feed_id"), maximum=255):
        return None, feed_err
    payload: dict[str, Any] = {"product_feed_id": product_set["product_feed_id"].strip()}
    if product_set.get("filters") is not None:
        filters, filters_err = _coerce_list(product_set.get("filters"), "product_set.filters")
        if filters_err:
            return None, filters_err
        seen_fields: set[str] = set()
        out: list[dict[str, Any]] = []
        for index, item in enumerate(filters or []):
            if not isinstance(item, dict):
                return None, _bad_request(f"product_set.filters[{index}] must be an object.")
            field = item.get("field")
            if not isinstance(field, str) or field.strip() not in _PRODUCT_SET_FILTER_FIELDS:
                return None, _bad_request(f"product_set.filters[{index}].field is not supported.")
            field = field.strip()
            if field in seen_fields:
                return None, _bad_request("product_set.filters must not repeat the same field.")
            seen_fields.add(field)
            operator = item.get("operator")
            if not isinstance(operator, str) or operator.strip() not in _PRODUCT_SET_FILTER_OPERATORS:
                return None, _bad_request("product_set filter operator must be in, gt, gte, lt, or lte.")
            operator = operator.strip()
            if operator != "in" and field not in _PRODUCT_SET_COMPARISON_FIELDS:
                return None, _bad_request("product_set comparison filters may only use price or star_rating.")
            values, values_err = _coerce_string_list(item.get("values"), f"product_set.filters[{index}].values")
            if values_err:
                return None, values_err
            if not values:
                return None, _bad_request(f"product_set.filters[{index}].values must include at least one value.")
            out.append({"field": field, "operator": operator, "values": values})
        payload["filters"] = out
    return payload, None


def _bid_multipliers_payload(value: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    entries, err = _coerce_list(value, "custom_audience_bid_multipliers")
    if err or entries is None:
        return None, err
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if isinstance(entry, str):
            entry, entry_err = _coerce_mapping(entry, f"custom_audience_bid_multipliers[{index}]")
            if entry_err:
                return None, entry_err
        if not isinstance(entry, dict):
            return None, _bad_request(f"custom_audience_bid_multipliers[{index}] must be an object.")
        if audience_err := _validate_non_empty(
            f"custom_audience_bid_multipliers[{index}].custom_audience_id", entry.get("custom_audience_id")
        ):
            return None, audience_err
        multiplier = entry.get("bid_multiplier")
        if not isinstance(multiplier, int | float) or isinstance(multiplier, bool):
            return None, _bad_request(f"custom_audience_bid_multipliers[{index}].bid_multiplier must be a number.")
        if range_err := _validate_float_range(
            f"custom_audience_bid_multipliers[{index}].bid_multiplier", float(multiplier), 0.1, 10
        ):
            return None, range_err
        out.append({
            "custom_audience_id": entry["custom_audience_id"].strip(),
            "bid_multiplier_micros": _to_micros(float(multiplier)),
        })
    return out, None


def _merge_current_bidding(sent: dict[str, Any], current: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Fill a partial bidding_config from the ad group's current one: the API replaces it whole."""
    current = current if isinstance(current, dict) else {}
    merged = dict(sent)
    strategy_changed = "strategy" in sent and sent["strategy"] != current.get("strategy")
    if "billing_event_type" not in merged and current.get("billing_event_type"):
        merged["billing_event_type"] = current["billing_event_type"]
    # automated_bid is a read-only strategy; leaving strategy out keeps AutoBid when no bid is sent.
    if "strategy" not in merged and current.get("strategy") in _BIDDING_STRATEGIES:
        merged["strategy"] = current["strategy"]
    # A strategy switch must not inherit the old bid (a fixed bid would become a surprise cap, and back).
    if "max_bid_micros" not in merged and current.get("max_bid_micros") and not strategy_changed:
        merged["max_bid_micros"] = current["max_bid_micros"]
    if "custom_audience_bid_multipliers" not in merged and current.get("custom_audience_bid_multipliers"):
        merged["custom_audience_bid_multipliers"] = [
            {"custom_audience_id": m["custom_audience_id"], "bid_multiplier_micros": m["bid_multiplier_micros"]}
            for m in current["custom_audience_bid_multipliers"]
            if isinstance(m, dict) and m.get("custom_audience_id") and m.get("bid_multiplier_micros")
        ]
    if "billing_event_type" not in merged:
        return None, _bad_request("billing_event is required: the ad group has no current billing event to keep.")
    if merged.get("strategy") == "fixed_bid" and "max_bid_micros" not in merged:
        return None, _bad_request("bidding_strategy fixed_bid requires max_bid.")
    return merged, None


def _build_ad_group_body(
    *,
    campaign_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    billing_event: str | None = None,
    max_bid: float | None = None,
    bidding_strategy: str | None = None,
    custom_audience_bid_multipliers: Any = None,
    context_hints: Any = None,
    product_set: Any = None,
    confirm_bid: bool = False,
    create: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    body: dict[str, Any] = {}
    if create:
        if campaign_err := _validate_non_empty("campaign_id", campaign_id):
            return None, campaign_err
        body["campaign_id"] = campaign_id
    if name is not None:
        if name_err := _validate_non_empty("name", name, minimum=3, maximum=1000):
            return None, name_err
        body["name"] = name.strip()
    elif create:
        return None, _bad_request("name is required.")
    if description is not None:
        body["description"] = description
    if status is not None:
        if status not in _AD_GROUP_STATUSES:
            return None, _bad_request("status must be active, paused, or archived.")
        if activation_err := _reject_activation_status(status, "create_ad_group" if create else "update_ad_group"):
            return None, activation_err
        if create and status != "paused":
            return None, _bad_request("Create tools only create paused ad groups. Use set_ad_group_state after review.")
        body["status"] = status
    elif create:
        body["status"] = "paused"
    multipliers, multipliers_err = _bid_multipliers_payload(custom_audience_bid_multipliers)
    if multipliers_err:
        return None, multipliers_err
    if (
        billing_event is not None
        or max_bid is not None
        or bidding_strategy is not None
        or multipliers is not None
    ):
        if create:
            # ponytail: max_bid is only optional for maximize_* strategies, so a create never silently falls back to AutoBid.
            bid_optional = bidding_strategy in {"maximize_clicks", "maximize_conversions"}
            if billing_event is None or (max_bid is None and not bid_optional):
                return None, _bad_request(
                    "billing_event and max_bid must be provided together "
                    "(max_bid is optional only with bidding_strategy maximize_clicks or maximize_conversions)."
                )
        bidding_config: dict[str, Any] = {}
        if billing_event is not None:
            if billing_event not in _BILLING_EVENTS:
                return None, _bad_request("billing_event must be impression or click.")
            bidding_config["billing_event_type"] = billing_event
        if bidding_strategy is not None:
            if strategy_err := _validate_option("bidding_strategy", bidding_strategy, _BIDDING_STRATEGIES):
                return None, strategy_err
            bidding_config["strategy"] = bidding_strategy
        if max_bid is not None:
            if bid_err := _validate_float_range("max_bid", float(max_bid), 0.000001, _MAX_BID):
                return None, bid_err
            if bid_err := _bid_guard(float(max_bid), confirm_bid):
                return None, bid_err
            bidding_config["max_bid_micros"] = _to_micros(float(max_bid))
        if multipliers is not None:
            bidding_config["custom_audience_bid_multipliers"] = multipliers
        body["bidding_config"] = bidding_config
    elif create:
        return None, _bad_request("billing_event and max_bid are required.")
    if context_hints is not None:
        hints, hints_err = _coerce_string_list(context_hints, "context_hints")
        if hints_err:
            return None, hints_err
        body["context_hints"] = hints
    parsed_product_set, product_set_err = _product_set_payload(product_set)
    if product_set_err:
        return None, product_set_err
    if parsed_product_set is not None:
        body["product_set"] = parsed_product_set
    if not body:
        return None, _bad_request("Provide at least one field to update.")
    return body, None


@ads_tool(open_world=True)
async def list_ad_groups(
    campaign_id: str,
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> str:
    """List ad groups, optionally filtered to a campaign.

    Args:
        campaign_id: Required parent campaign id.
        limit: Results per page, 1-500. Default 20.
        after: Optional cursor for forward pagination.
        before: Optional cursor for backward pagination.
        order: Sort order, asc or desc. Default desc.
    """
    if campaign_err := _validate_non_empty("campaign_id", campaign_id):
        return campaign_err
    if limit_err := _validate_int_range("limit", limit, 1, 500):
        return limit_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    params = _optional_params(campaign_id=campaign_id, limit=limit, after=after, before=before, order=order)
    try:
        return _ok(await client.get("/ad_groups", params=params))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(open_world=True)
async def get_ad_group(ad_group_id: str) -> str:
    """Get one ad group by id."""
    if ad_group_err := _validate_non_empty("ad_group_id", ad_group_id):
        return ad_group_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.get(f"/ad_groups/{ad_group_id}"))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, open_world=True)
async def create_ad_group(
    campaign_id: str,
    name: str,
    billing_event: Literal["impression", "click"],
    max_bid: float | None = None,
    status: Literal["paused"] = "paused",
    description: str | None = None,
    bidding_strategy: Literal["fixed_bid", "maximize_clicks", "maximize_conversions"] | None = None,
    custom_audience_bid_multipliers: Any = None,
    context_hints: Any = None,
    product_set: Any = None,
    idempotency_key: str | None = None,
    confirm_bid: bool = False,
    max_bid_usd: float | None = None,
) -> str:
    """Create a paused ad group under a campaign.

    Args:
        campaign_id: Parent campaign id.
        name: Ad group name, 3-1000 characters.
        billing_event: impression or click.
        max_bid: Max bid in the ad account's currency, major units (1.5 = ₹1.50 or $1.50;
            see get_account), sent as micros. Must be > 0 and within the API maximum (30,400,000). Required
            unless bidding_strategy is maximize_clicks or maximize_conversions, where it acts as a bid cap.
        status: Must be paused. To go live, call set_ad_group_state after review.
        description: Optional internal description.
        bidding_strategy: Optional fixed_bid, maximize_clicks, or maximize_conversions.
        custom_audience_bid_multipliers: Optional list of {"custom_audience_id": "...", "bid_multiplier": 1.5},
            multiplier between 0.1 and 10.
        context_hints: Optional list of strings that steer matching context.
        idempotency_key: Optional; a fresh one is generated when omitted (maximize_* strategies require one).
        confirm_bid: Required when max_bid exceeds OPENAI_ADS_BID_CEILING (account-currency major units, default 10).
        max_bid_usd: Removed; use max_bid.
    """
    if renamed_err := _reject_renamed(max_bid_usd=max_bid_usd):
        return renamed_err
    body, body_err = _build_ad_group_body(
        campaign_id=campaign_id,
        name=name,
        description=description,
        status=status,
        billing_event=billing_event,
        max_bid=max_bid,
        bidding_strategy=bidding_strategy,
        custom_audience_bid_multipliers=custom_audience_bid_multipliers,
        context_hints=context_hints,
        product_set=product_set,
        confirm_bid=confirm_bid,
        create=True,
    )
    if body_err:
        return body_err
    idempotency_key, idempotency_err = _validate_idempotency_key(idempotency_key)
    if idempotency_err:
        return idempotency_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        kwargs = {"json": body}
        if idempotency_key:
            kwargs["idempotency_key"] = idempotency_key
        return _ok(await client.post("/ad_groups", **kwargs))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, open_world=True)
async def update_ad_group(
    ad_group_id: str,
    name: str | None = None,
    billing_event: Literal["impression", "click"] | None = None,
    max_bid: float | None = None,
    status: Literal["paused", "archived"] | None = None,
    description: str | None = None,
    bidding_strategy: Literal["fixed_bid", "maximize_clicks", "maximize_conversions"] | None = None,
    custom_audience_bid_multipliers: Any = None,
    context_hints: Any = None,
    product_set: Any = None,
    confirm_bid: bool = False,
    max_bid_usd: float | None = None,
) -> str:
    """Update ad group fields, including bid and context hints.

    max_bid is in the ad account's currency, major units, like campaign budgets;
    above OPENAI_ADS_BID_CEILING (default 10) it needs confirm_bid=True. Any
    bidding change (billing_event, max_bid, bidding_strategy,
    custom_audience_bid_multipliers) reads the ad group first and resends its
    current billing event, strategy, bid and multipliers for whatever you leave
    out, so changing one never resets the others. fixed_bid needs a max_bid.
    max_bid_usd was renamed to max_bid and is refused.
    """
    if ad_group_err := _validate_non_empty("ad_group_id", ad_group_id):
        return ad_group_err
    if renamed_err := _reject_renamed(max_bid_usd=max_bid_usd):
        return renamed_err
    body, body_err = _build_ad_group_body(
        name=name,
        description=description,
        status=status,
        billing_event=billing_event,
        max_bid=max_bid,
        bidding_strategy=bidding_strategy,
        custom_audience_bid_multipliers=custom_audience_bid_multipliers,
        context_hints=context_hints,
        product_set=product_set,
        confirm_bid=confirm_bid,
    )
    if body_err:
        return body_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if "bidding_config" in body:
            current = (await client.get(f"/ad_groups/{ad_group_id}")).get("bidding_config")
            merged, merge_err = _merge_current_bidding(body["bidding_config"], current)
            if merge_err:
                return merge_err
            body["bidding_config"] = merged
        return _ok(await client.post(f"/ad_groups/{ad_group_id}", json=body))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def set_ad_group_state(
    ad_group_id: str,
    state: Literal["activate", "pause", "archive"],
) -> str:
    """Activate, pause, or archive an ad group.

    Activation can start delivery when the parent campaign and child ads are
    also active, so call this only after review.
    """
    if ad_group_err := _validate_non_empty("ad_group_id", ad_group_id):
        return ad_group_err
    if state_err := _validate_option("state", state, _AD_GROUP_STATES):
        return state_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post(f"/ad_groups/{ad_group_id}/{state}"))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = (
    "list_ad_groups",
    "get_ad_group",
    "create_ad_group",
    "update_ad_group",
    "set_ad_group_state",
    "_build_ad_group_body",
)

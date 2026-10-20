"""Campaign MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *

_CAMPAIGN_STATES = {"activate", "pause", "archive"}
_CAMPAIGN_STATUSES = {"active", "paused", "archived"}
_CAMPAIGN_BIDDING_TYPES = {"impressions", "clicks", "conversions"}
_CAMPAIGN_PLATFORMS = {"ios_app", "android_app", "web", "desktop_web", "ios_web", "android_web"}


def _locations_include(locations: Any, name: str) -> tuple[dict[str, Any] | None, str | None]:
    entries, err = _coerce_list(locations, name)
    if err:
        return None, err
    include = []
    for entry in entries or []:
        if isinstance(entry, str):
            include.append({"id": entry})
        elif isinstance(entry, dict):
            if not entry.get("id"):
                return None, _bad_request(f"Each {name} object must include id.")
            include.append(entry)
        else:
            return None, _bad_request(f"{name} must contain location ids or objects.")
    return {"include": include}, None


def _geo_params(geo: Any) -> dict[str, Any] | None:
    """Turn a campaign's returned geo block back into request params (include entries by id)."""
    if not isinstance(geo, dict):
        return None
    out: dict[str, Any] = {}
    if include := [{"id": e["id"]} for e in geo.get("include") or [] if isinstance(e, dict) and e.get("id")]:
        out["include"] = include
    if countries := geo.get("countries"):
        out["countries"] = countries
    return out or None


def _targeting_payload(
    locations: Any = None,
    excluded_locations: Any = None,
    custom_audience_ids: Any = None,
    excluded_custom_audience_ids: Any = None,
    platforms: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    targeting: dict[str, Any] = {}
    for key, value in (("locations", locations), ("excluded_locations", excluded_locations)):
        if value is not None:
            parsed, err = _locations_include(value, key)
            if err:
                return None, err
            targeting[key] = parsed
    for key, name, value in (
        ("custom_audiences", "custom_audience_ids", custom_audience_ids),
        ("excluded_custom_audiences", "excluded_custom_audience_ids", excluded_custom_audience_ids),
    ):
        ids, err = _coerce_string_list(value, name)
        if err:
            return None, err
        if ids is not None:
            targeting[key] = {"ids": ids}
    platform_values, err = _coerce_string_list(platforms, "platforms")
    if err:
        return None, err
    if platform_values is not None:
        if unknown := [item for item in platform_values if item not in _CAMPAIGN_PLATFORMS]:
            return None, _bad_request(
                f"Invalid platforms: {', '.join(unknown)}. Allowed values: {', '.join(sorted(_CAMPAIGN_PLATFORMS))}."
            )
        targeting["platforms"] = {"included": platform_values}
    return targeting or None, None


def _build_campaign_body(
    *,
    name: str | None = None,
    lifetime_budget: float | None = None,
    daily_budget: float | None = None,
    status: str | None = None,
    description: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    mode: str | None = None,
    bidding_type: str | None = None,
    conversion_event_setting_ids: Any = None,
    locations: Any = None,
    excluded_locations: Any = None,
    custom_audience_ids: Any = None,
    excluded_custom_audience_ids: Any = None,
    platforms: Any = None,
    confirm_budget: bool = False,
    create: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    body: dict[str, Any] = {}
    if name is not None:
        if name_err := _validate_non_empty("name", name, minimum=3, maximum=1000):
            return None, name_err
        body["name"] = name.strip()
    elif create:
        return None, _bad_request("name is required.")

    if status is not None:
        if status not in _CAMPAIGN_STATUSES:
            return None, _bad_request("status must be active, paused, or archived.")
        if activation_err := _reject_activation_status(status, "create_campaign" if create else "update_campaign"):
            return None, activation_err
        if create and status != "paused":
            return None, _bad_request("Create tools only create paused campaigns. Use set_campaign_state after review.")
        body["status"] = status
    elif create:
        body["status"] = "paused"

    if lifetime_budget is not None and daily_budget is not None:
        return None, _bad_request("Set lifetime_budget or daily_budget, not both: OpenAI Ads rejects both on one campaign.")
    budget: dict[str, int] = {}
    if lifetime_budget is not None:
        if budget_err := _budget_guard(float(lifetime_budget), confirm_budget, "lifetime_budget"):
            return None, budget_err
        budget["lifetime_spend_limit_micros"] = _to_micros(float(lifetime_budget))
    if daily_budget is not None:
        if budget_err := _daily_budget_guard(float(daily_budget), confirm_budget, start_time, end_time):
            return None, budget_err
        budget["daily_spend_limit_micros"] = _to_micros(float(daily_budget))
    if budget:
        body["budget"] = budget
    elif create:
        return None, _bad_request("lifetime_budget or daily_budget is required.")

    if description is not None:
        body["description"] = description
    if start_err := _validate_unix_time("start_time", start_time):
        return None, start_err
    if end_err := _validate_unix_time("end_time", end_time):
        return None, end_err
    if start_time is not None:
        body["start_time"] = start_time
    if end_time is not None:
        body["end_time"] = end_time
    if start_time is not None and end_time is not None and end_time <= start_time:
        return None, _bad_request("end_time must be after start_time.")
    if mode is not None:
        if not create:
            return None, _bad_request("mode cannot be changed after campaign creation.")
        if mode != "product_feed":
            return None, _bad_request("mode must be product_feed when provided.")
        body["mode"] = mode
    if bidding_type is not None:
        if not create:
            return None, _bad_request("bidding_type cannot be changed after campaign creation.")
        if bidding_type not in _CAMPAIGN_BIDDING_TYPES:
            return None, _bad_request("bidding_type must be impressions, clicks, or conversions.")
        body["bidding_type"] = bidding_type
    conversion_ids, conversion_ids_err = _coerce_string_list(
        conversion_event_setting_ids,
        "conversion_event_setting_ids",
    )
    if conversion_ids_err:
        return None, conversion_ids_err
    if conversion_ids is not None:
        if len(conversion_ids) != 1:
            return None, _bad_request("conversion_event_setting_ids must contain exactly one event setting id.")
        body["conversion_event_setting_ids"] = conversion_ids
    if create and bidding_type == "conversions":
        if mode == "product_feed":
            return None, _bad_request("Conversion-optimized campaigns cannot use product_feed mode.")
        if conversion_ids is None:
            return None, _bad_request("bidding_type='conversions' requires exactly one conversion_event_setting_ids value.")
    elif create and conversion_ids is not None:
        return None, _bad_request("conversion_event_setting_ids requires bidding_type='conversions' when creating a campaign.")
    targeting, targeting_err = _targeting_payload(
        locations,
        excluded_locations,
        custom_audience_ids,
        excluded_custom_audience_ids,
        platforms,
    )
    if targeting_err:
        return None, targeting_err
    if targeting is not None:
        body["targeting"] = targeting
    if not body:
        return None, _bad_request("Provide at least one field to update.")
    return body, None


@ads_tool(open_world=True)
async def list_campaigns(
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> str:
    """List campaigns in the authenticated ad account.

    Args:
        limit: Results per page, 1-500. Default 20.
        after: Optional cursor for forward pagination.
        before: Optional cursor for backward pagination.
        order: Sort order, asc or desc. Default desc.
    """
    if limit_err := _validate_int_range("limit", limit, 1, 500):
        return limit_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    params = _optional_params(limit=limit, after=after, before=before, order=order)
    try:
        return _ok(await client.get("/campaigns", params=params))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(open_world=True)
async def get_campaign(campaign_id: str) -> str:
    """Get one campaign by id."""
    if campaign_err := _validate_non_empty("campaign_id", campaign_id):
        return campaign_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.get(f"/campaigns/{campaign_id}"))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def create_campaign(
    name: str,
    lifetime_budget: float | None = None,
    daily_budget: float | None = None,
    status: Literal["paused"] = "paused",
    description: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    mode: Literal["product_feed"] | None = None,
    bidding_type: Literal["impressions", "clicks", "conversions"] | None = None,
    conversion_event_setting_ids: Any = None,
    locations: Any = None,
    excluded_locations: Any = None,
    custom_audience_ids: Any = None,
    excluded_custom_audience_ids: Any = None,
    platforms: Any = None,
    confirm_budget: bool = False,
    idempotency_key: str | None = None,
    budget_usd: float | None = None,
    daily_budget_usd: float | None = None,
) -> str:
    """Create an OpenAI Ads campaign, always safely paused by default.

    Args:
        name: Campaign name, 3-1000 characters.
        lifetime_budget: Lifetime spend limit in the ad account's currency, major units
            (500 = ₹500 on an INR account, $500 on a USD account; call get_account to see the currency).
            Provide this or daily_budget, not both.
        daily_budget: Daily spend limit in the ad account's currency, major units. The API enforces
            a per-currency minimum (for example ₹500 on INR accounts). Needs confirm_budget=True unless
            end_time is set and daily_budget × days until end_time stays within OPENAI_ADS_BUDGET_CEILING.
        status: Must be paused. To go live, call set_campaign_state after review.
        description: Optional internal campaign description.
        start_time: Optional Unix timestamp, 2000-01-01 to 2100-01-01.
        end_time: Optional Unix timestamp, 2000-01-01 to 2100-01-01.
        mode: Optional. Only product_feed is supported.
        bidding_type: impressions, clicks, or conversions. Conversion optimization requires one event setting id.
        conversion_event_setting_ids: Exactly one active standard conversion event for conversion optimization.
        locations: Optional geo target ids or objects for targeting.locations.include (see search_geo).
        excluded_locations: Optional geo target ids or objects to exclude.
        custom_audience_ids: Optional custom audience ids to target.
        excluded_custom_audience_ids: Optional custom audience ids to exclude.
        platforms: Optional list of ios_app, android_app, web, desktop_web, ios_web, android_web.
        confirm_budget: Required when lifetime_budget exceeds OPENAI_ADS_BUDGET_CEILING (account-currency
            major units, default 100), or for a daily_budget that could total more than it (see daily_budget).
        idempotency_key: Optional; a fresh one is generated when omitted.
        budget_usd, daily_budget_usd: Removed; use lifetime_budget or daily_budget.
    """
    if renamed_err := _reject_renamed(budget_usd=budget_usd, daily_budget_usd=daily_budget_usd):
        return renamed_err
    body, body_err = _build_campaign_body(
        name=name,
        lifetime_budget=lifetime_budget,
        daily_budget=daily_budget,
        status=status,
        description=description,
        start_time=start_time,
        end_time=end_time,
        mode=mode,
        bidding_type=bidding_type,
        conversion_event_setting_ids=conversion_event_setting_ids,
        locations=locations,
        excluded_locations=excluded_locations,
        custom_audience_ids=custom_audience_ids,
        excluded_custom_audience_ids=excluded_custom_audience_ids,
        platforms=platforms,
        confirm_budget=confirm_budget,
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
        return _ok(await client.post("/campaigns", **kwargs))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def update_campaign(
    campaign_id: str,
    name: str | None = None,
    lifetime_budget: float | None = None,
    daily_budget: float | None = None,
    status: Literal["paused", "archived"] | None = None,
    description: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    conversion_event_setting_ids: Any = None,
    locations: Any = None,
    excluded_locations: Any = None,
    custom_audience_ids: Any = None,
    excluded_custom_audience_ids: Any = None,
    platforms: Any = None,
    confirm_budget: bool = False,
    budget_usd: float | None = None,
    daily_budget_usd: float | None = None,
) -> str:
    """Update campaign fields.

    Budget changes (lifetime_budget or daily_budget, not both, as amounts in the
    ad account's currency, major units; see get_account) are guarded by
    OPENAI_ADS_BUDGET_CEILING: a daily_budget needs confirm_budget=True unless
    end_time is passed and daily_budget × days until it stays within the
    ceiling. budget_usd and daily_budget_usd were renamed and are refused. Activation is not allowed here; use
    set_campaign_state after review. bidding_type and mode cannot be changed
    after creation. Targeting arguments match create_campaign.

    locations and excluded_locations are replaced as a pair by the API, so when
    only one is given the campaign is read first and the other keeps its current
    value. Audience and platform targeting change only when passed.
    """
    if campaign_err := _validate_non_empty("campaign_id", campaign_id):
        return campaign_err
    if renamed_err := _reject_renamed(budget_usd=budget_usd, daily_budget_usd=daily_budget_usd):
        return renamed_err
    body, body_err = _build_campaign_body(
        name=name,
        lifetime_budget=lifetime_budget,
        daily_budget=daily_budget,
        status=status,
        description=description,
        start_time=start_time,
        end_time=end_time,
        conversion_event_setting_ids=conversion_event_setting_ids,
        locations=locations,
        excluded_locations=excluded_locations,
        custom_audience_ids=custom_audience_ids,
        excluded_custom_audience_ids=excluded_custom_audience_ids,
        platforms=platforms,
        confirm_budget=confirm_budget,
    )
    if body_err:
        return body_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if (locations is None) != (excluded_locations is None):
            # The API rewrites targeting geo as a pair: sending one side alone wipes the other.
            other = "locations" if locations is None else "excluded_locations"
            current = ((await client.get(f"/campaigns/{campaign_id}")).get("targeting") or {}).get(other)
            if current := _geo_params(current):
                body["targeting"][other] = current
        return _ok(await client.post(f"/campaigns/{campaign_id}", json=body))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def set_campaign_state(
    campaign_id: str,
    state: Literal["activate", "pause", "archive"],
) -> str:
    """Activate, pause, or archive a campaign.

    Activation can start real spend once its ad groups and ads are also active.
    Call it only after the user has reviewed the campaign tree and budget.
    """
    if campaign_err := _validate_non_empty("campaign_id", campaign_id):
        return campaign_err
    if state_err := _validate_option("state", state, _CAMPAIGN_STATES):
        return state_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post(f"/campaigns/{campaign_id}/{state}"))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = (
    "list_campaigns",
    "get_campaign",
    "create_campaign",
    "update_campaign",
    "set_campaign_state",
    "_build_campaign_body",
)

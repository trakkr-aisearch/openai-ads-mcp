"""Ad group MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *

_AD_GROUP_STATES = {"activate", "pause", "archive"}
_AD_GROUP_STATUSES = {"active", "paused", "archived"}
_BILLING_EVENTS = {"impression", "click"}


def _build_ad_group_body(
    *,
    campaign_id: str | None = None,
    name: str | None = None,
    status: str | None = None,
    billing_event: str | None = None,
    max_bid_usd: float | None = None,
    context_hints: Any = None,
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
    if status is not None:
        if status not in _AD_GROUP_STATUSES:
            return None, _bad_request("status must be active, paused, or archived.")
        if create and status != "paused":
            return None, _bad_request("Create tools only create paused ad groups. Use set_ad_group_state after review.")
        body["status"] = status
    elif create:
        body["status"] = "paused"
    if billing_event is not None or max_bid_usd is not None:
        if billing_event is None or max_bid_usd is None:
            return None, _bad_request("billing_event and max_bid_usd must be provided together.")
        if billing_event not in _BILLING_EVENTS:
            return None, _bad_request("billing_event must be impression or click.")
        if bid_err := _validate_float_range("max_bid_usd", float(max_bid_usd), 0.000001, 100):
            return None, bid_err
        body["bidding_config"] = {
            "billing_event_type": billing_event,
            "max_bid_micros": _usd_to_micros(float(max_bid_usd)),
        }
    elif create:
        return None, _bad_request("billing_event and max_bid_usd are required.")
    if context_hints is not None:
        hints, hints_err = _coerce_string_list(context_hints, "context_hints")
        if hints_err:
            return None, hints_err
        body["context_hints"] = hints
    if not body:
        return None, _bad_request("Provide at least one field to update.")
    return body, None


@ads_tool()
async def list_ad_groups(
    campaign_id: str | None = None,
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> str:
    """List ad groups, optionally filtered to a campaign.

    Args:
        campaign_id: Optional campaign id. The OpenAI API commonly expects this filter.
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
    params = _optional_params(campaign_id=campaign_id, limit=limit, after=after, before=before, order=order)
    try:
        return _ok(await client.get("/ad_groups", params=params))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool()
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


@ads_tool(writes=True)
async def create_ad_group(
    campaign_id: str,
    name: str,
    billing_event: Literal["impression", "click"],
    max_bid_usd: float,
    status: Literal["paused", "active"] = "paused",
    context_hints: Any = None,
) -> str:
    """Create a paused ad group under a campaign.

    Args:
        campaign_id: Parent campaign id.
        name: Ad group name, 3-1000 characters.
        billing_event: impression or click.
        max_bid_usd: Max bid converted to micros. Must be > 0 and <= 100.
        status: Must be paused. To go live, call set_ad_group_state after review.
        context_hints: Optional list of strings that steer matching context.
    """
    body, body_err = _build_ad_group_body(
        campaign_id=campaign_id,
        name=name,
        status=status,
        billing_event=billing_event,
        max_bid_usd=max_bid_usd,
        context_hints=context_hints,
        create=True,
    )
    if body_err:
        return body_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post("/ad_groups", json=body))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True)
async def update_ad_group(
    ad_group_id: str,
    name: str | None = None,
    billing_event: Literal["impression", "click"] | None = None,
    max_bid_usd: float | None = None,
    status: Literal["active", "paused", "archived"] | None = None,
    context_hints: Any = None,
) -> str:
    """Update ad group fields, including bid and context hints."""
    if ad_group_err := _validate_non_empty("ad_group_id", ad_group_id):
        return ad_group_err
    body, body_err = _build_ad_group_body(
        name=name,
        status=status,
        billing_event=billing_event,
        max_bid_usd=max_bid_usd,
        context_hints=context_hints,
    )
    if body_err:
        return body_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
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

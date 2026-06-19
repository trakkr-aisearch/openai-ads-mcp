"""Campaign MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *

_CAMPAIGN_STATES = {"activate", "pause", "archive"}
_CAMPAIGN_STATUSES = {"active", "paused", "archived"}


def _locations_payload(locations: Any) -> tuple[dict[str, Any] | None, str | None]:
    if locations is None:
        return None, None
    entries, err = _coerce_list(locations, "locations")
    if err:
        return None, err
    include = []
    for entry in entries or []:
        if isinstance(entry, str):
            include.append({"id": entry})
        elif isinstance(entry, dict):
            if not entry.get("id"):
                return None, _bad_request("Each location object must include id.")
            include.append(entry)
        else:
            return None, _bad_request("locations must contain location ids or objects.")
    return {"locations": {"include": include}}, None


def _build_campaign_body(
    *,
    name: str | None = None,
    budget_usd: float | None = None,
    status: str | None = None,
    description: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    mode: str | None = None,
    locations: Any = None,
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
        if create and status != "paused":
            return None, _bad_request("Create tools only create paused campaigns. Use set_campaign_state after review.")
        body["status"] = status
    elif create:
        body["status"] = "paused"

    if budget_usd is not None:
        if budget_err := _budget_guard(float(budget_usd), confirm_budget):
            return None, budget_err
        body["budget"] = {"lifetime_spend_limit_micros": _usd_to_micros(float(budget_usd))}
    elif create:
        return None, _bad_request("budget_usd is required.")

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
        if mode != "product_feed":
            return None, _bad_request("mode must be product_feed when provided.")
        body["mode"] = mode
    targeting, targeting_err = _locations_payload(locations)
    if targeting_err:
        return None, targeting_err
    if targeting is not None:
        body["targeting"] = targeting
    if not body:
        return None, _bad_request("Provide at least one field to update.")
    return body, None


@ads_tool()
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


@ads_tool()
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
    budget_usd: float,
    status: Literal["paused", "active"] = "paused",
    description: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    mode: Literal["product_feed"] | None = None,
    locations: Any = None,
    confirm_budget: bool = False,
) -> str:
    """Create an OpenAI Ads campaign, always safely paused by default.

    Args:
        name: Campaign name, 3-1000 characters.
        budget_usd: Lifetime spend limit in USD. Minimum 1.00.
        status: Must be paused. To go live, call set_campaign_state after review.
        description: Optional internal campaign description.
        start_time: Optional Unix timestamp, 2000-01-01 to 2100-01-01.
        end_time: Optional Unix timestamp, 2000-01-01 to 2100-01-01.
        mode: Optional. Only product_feed is supported.
        locations: Optional geo target entries for targeting.locations.include.
        confirm_budget: Required when budget_usd exceeds OPENAI_ADS_BUDGET_CEILING_USD.
    """
    body, body_err = _build_campaign_body(
        name=name,
        budget_usd=budget_usd,
        status=status,
        description=description,
        start_time=start_time,
        end_time=end_time,
        mode=mode,
        locations=locations,
        confirm_budget=confirm_budget,
        create=True,
    )
    if body_err:
        return body_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post("/campaigns", json=body))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def update_campaign(
    campaign_id: str,
    name: str | None = None,
    budget_usd: float | None = None,
    status: Literal["active", "paused", "archived"] | None = None,
    description: str | None = None,
    start_time: int | None = None,
    end_time: int | None = None,
    mode: Literal["product_feed"] | None = None,
    locations: Any = None,
    confirm_budget: bool = False,
) -> str:
    """Update campaign fields.

    Budget changes are guarded by OPENAI_ADS_BUDGET_CEILING_USD. If you set
    status to active here, this can start real spend, so prefer
    set_campaign_state for explicit activation.
    """
    if campaign_err := _validate_non_empty("campaign_id", campaign_id):
        return campaign_err
    body, body_err = _build_campaign_body(
        name=name,
        budget_usd=budget_usd,
        status=status,
        description=description,
        start_time=start_time,
        end_time=end_time,
        mode=mode,
        locations=locations,
        confirm_budget=confirm_budget,
    )
    if body_err:
        return body_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
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

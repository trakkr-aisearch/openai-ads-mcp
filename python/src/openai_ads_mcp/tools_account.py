"""Account-level OpenAI Ads MCP tools."""

from __future__ import annotations

from ._core import *

_AD_ACCOUNT_STATES = {"activate", "pause"}


@ads_tool(open_world=True)
async def get_account() -> str:
    """Get the authenticated OpenAI Ads account.

    This is the first tool to call after connecting. It verifies that
    OPENAI_ADS_API_KEY is valid and returns the ad account id, name, timezone,
    currency, and settings for the one account attached to the key.
    """
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.get("/ad_account"))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def set_ad_account_state(state: Literal["activate", "pause"]) -> str:
    """Activate or pause the whole ad account.

    Pausing stops delivery for every campaign in the account. Activating can
    resume real spend on every active campaign, so call it only when the user
    explicitly asks.
    """
    if state_err := _validate_option("state", state, _AD_ACCOUNT_STATES):
        return state_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post(f"/ad_account/{state}"))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, open_world=True)
async def update_ad_account_brand(
    name: str | None = None,
    legal_name: str | None = None,
    account_name: str | None = None,
    brand_name: str | None = None,
    url: str | None = None,
    favicon_file_id: str | None = None,
) -> str:
    """Update the ad account's brand details shown with its ads.

    Args:
        name: Optional account display name.
        legal_name: Optional legal business name.
        account_name: Optional ad account name.
        brand_name: Optional brand name shown to users.
        url: Optional brand website, 1-2048 characters.
        favicon_file_id: Optional file_id from upload_creative with purpose='account_favicon'.
    """
    values = {
        "name": name,
        "legal_name": legal_name,
        "account_name": account_name,
        "brand_name": brand_name,
        "url": url,
        "favicon_file_id": favicon_file_id,
    }
    body: dict[str, Any] = {}
    for field, value in values.items():
        if value is None:
            continue
        if field_err := _validate_non_empty(field, value, maximum=2048 if field == "url" else 500):
            return field_err
        body[field] = value.strip()
    if not body:
        return _bad_request("Provide at least one field to update.")
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post("/ad_account/brand", json=body))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = ("get_account", "set_ad_account_state", "update_ad_account_brand")

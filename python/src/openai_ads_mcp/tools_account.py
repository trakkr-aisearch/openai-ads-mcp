"""Account-level OpenAI Ads MCP tools."""

from __future__ import annotations

from ._core import *


@ads_tool()
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


__all__ = ("get_account",)

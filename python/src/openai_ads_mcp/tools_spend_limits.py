"""Account daily spend limit MCP tools for OpenAI Ads."""

from __future__ import annotations

import math
import re
from typing import Any

from ._core import *

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _rules(current: dict[str, Any]) -> list[dict[str, Any]]:
    """Active and upcoming daily rules; falls back to the singleton daily_limit."""
    rules = current.get("daily_limits")
    if rules is None:
        rules = [current["daily_limit"]] if current.get("daily_limit") else []
    return [r for r in rules if isinstance(r, dict)]


def _ambiguous(rules: list[dict[str, Any]]) -> str:
    listing = "; ".join(
        f"window_id={r.get('window_id')} amount={(r.get('amount_micros') or 0) / 1_000_000:g} "
        f"start_date={r.get('start_date')} status={r.get('status')}"
        for r in rules
    )
    return _bad_request(
        f"This account has {len(rules)} daily spend limit rules ({listing}). Only one can be changed at a time."
    )


@ads_tool(open_world=True)
async def get_spend_limits() -> str:
    """Get the ad account's spend limit windows: the daily limit (none when it is missing), its window_id,
    the revision, the earliest start date, and whether a daily limit can be created."""
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.get("/ad_account/spend_limit_windows"))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def set_daily_spend_limit(amount: float, end_date: str | None = None) -> str:
    """Set or change the ad account's daily spend limit across every campaign.

    amount is in the ad account's currency (major units, 0 or more). end_date (YYYY-MM-DD, exclusive)
    is optional.

    Requires invoice (postpaid) billing. A first activation takes effect from the next account-local
    day, and a decrease below today's recorded spend is rejected.
    """
    if not math.isfinite(amount) or amount < 0:
        return _bad_request("amount must be a number of at least 0 in the ad account's currency.")
    if end_date is not None and not _DATE_RE.fullmatch(end_date):
        return _bad_request("end_date must be a date in YYYY-MM-DD format.")
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        current = await client.get("/ad_account/spend_limit_windows")
        rules = _rules(current)
        if len(rules) > 1:
            return _ambiguous(rules)
        # revision can be absent because _compact drops nulls; the spec says to use 0 then.
        body: dict[str, Any] = {"amount_micros": _to_micros(amount), "expected_revision": current.get("revision", 0)}
        if rules and rules[0].get("window_id"):
            body["window_id"] = rules[0]["window_id"]
        elif current.get("earliest_daily_start_date"):
            # Recreating a removed or expired limit requires a start_date.
            body["start_date"] = current["earliest_daily_start_date"]
        if end_date:
            body["end_date"] = end_date
        return _ok(await client.post("/ad_account/daily_spend_limit", json=body))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def remove_daily_spend_limit() -> str:
    """Remove the ad account's daily spend limit, leaving spend capped only by campaign budgets.

    Requires invoice (postpaid) billing. Removal takes effect from the next account-local day.
    """
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        current = await client.get("/ad_account/spend_limit_windows")
        rules = _rules(current)
        if len(rules) > 1:
            return _ambiguous(rules)
        if not rules or not rules[0].get("window_id"):
            return _bad_request("This account has no daily spend limit to remove.")
        body = {"expected_revision": current.get("revision", 0), "window_id": rules[0]["window_id"]}
        return _ok(await client.post("/ad_account/daily_spend_limit/delete", json=body))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = ("get_spend_limits", "set_daily_spend_limit", "remove_daily_spend_limit")

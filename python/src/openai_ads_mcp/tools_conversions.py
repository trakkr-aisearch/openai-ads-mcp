"""Conversion management and ingest MCP tools for OpenAI Ads."""

from __future__ import annotations

import re
from ipaddress import ip_address

from ._core import *
from .tools_insights import _normalize_time_range

_ACTION_SOURCES = {"web", "mobile_app", "offline", "physical_store", "phone_call", "email", "other"}
_CONVERSION_AGGREGATION_LEVELS = {"campaign", "ad_group", "ad"}
_SUPPORTED_EVENT_DATA_TYPES = {
    "app_installed": "customer_action",
    "app_opened": "customer_action",
    "appointment_scheduled": "customer_action",
    "checkout_started": "contents",
    "contents_viewed": "contents",
    "custom": "custom",
    "items_added": "contents",
    "lead_created": "customer_action",
    "order_created": "contents",
    "page_viewed": "contents",
    "registration_completed": "customer_action",
    "subscription_created": "plan_enrollment",
    "trial_started": "plan_enrollment",
}
_BUILT_IN_EVENT_NAMES = set(_SUPPORTED_EVENT_DATA_TYPES) - {"custom"}
_USER_FIELDS = {"email_sha256", "external_id_sha256", "country", "city", "zip_code", "ip_address", "user_agent", "obref"}
_EVENT_DATA_FIELDS = {
    "contents": {"type", "amount", "currency", "contents"},
    "customer_action": {"type", "amount", "currency"},
    "plan_enrollment": {"type", "plan_id", "amount", "currency", "contents"},
    "custom": {"type", "plan_id", "amount", "currency", "contents"},
}
_CONTENT_FIELDS = {"id", "name", "content_type", "quantity", "amount", "currency"}
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_CUSTOM_EVENT_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _source_ids_payload(source_ids: Any) -> tuple[list[str] | None, str | None]:
    ids, err = _coerce_string_list(source_ids, "source_ids")
    if err:
        return None, err
    if not ids:
        return None, _bad_request("source_ids must include at least one id.")
    return ids, None


@ads_tool(open_world=True)
async def get_conversions(
    action: Literal["get_event_settings", "get_insights"],
    aggregation_level: Literal["campaign", "ad_group", "ad"] | None = None,
    time_ranges: Any = None,
    entity_ids: Any = None,
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> str:
    """Read conversion setup and conversion reporting. Never changes the account.

    Actions:
    - get_event_settings: GET /conversions/event_settings (paged with limit, after, before, order).
    - get_insights: POST /conversions/insights (a read despite the POST). Requires
      aggregation_level (campaign, ad_group, or ad) and time_ranges. Pass
      entity_ids for per-entity rows; omit it for one total across the account
      (sent as group_by_entity=false, which the API requires without entity_ids).

    time_ranges is a list of range objects (or JSON strings). Prefer a date_range
    in the ad account's timezone (call get_account to read it), for example
    {"type":"date_range","since":"2026-10-12","until":"2026-10-19","timezone":"Asia/Kolkata"}.
    """
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if action == "get_event_settings":
            if limit_err := _validate_int_range("limit", limit, 1, 500):
                return limit_err
            params = _optional_params(limit=limit, after=after, before=before, order=order)
            return _ok(await client.get("/conversions/event_settings", params=params))
        if action == "get_insights":
            if aggregation_level is None:
                return _bad_request("aggregation_level is required for get_insights: campaign, ad_group, or ad.")
            if level_err := _validate_option("aggregation_level", aggregation_level, _CONVERSION_AGGREGATION_LEVELS):
                return level_err
            if isinstance(time_ranges, dict) or (isinstance(time_ranges, str) and time_ranges.strip().startswith("{")):
                time_ranges = [time_ranges]
            items, ranges_err = _coerce_list(time_ranges, "time_ranges")
            if ranges_err:
                return ranges_err
            if not items:
                return _bad_request("time_ranges is required for get_insights.")
            ranges = []
            for item in items:
                time_range, range_err = _coerce_mapping(item, "time_ranges item")
                if range_err:
                    return range_err
                time_range, range_err = _normalize_time_range(time_range)
                if range_err:
                    return range_err
                ranges.append(json.dumps(time_range, separators=_COMPACT_SEPARATORS))
            ids, ids_err = _coerce_string_list(entity_ids, "entity_ids")
            if ids_err:
                return ids_err
            body: dict[str, Any] = {"aggregation_level": aggregation_level, "time_ranges": ranges}
            if ids:
                body["entity_ids"] = ids
            else:
                # The API defaults group_by_entity to true, then 400s with "entity_ids must be provided".
                body["group_by_entity"] = False
            return _ok(await client.post("/conversions/insights", json=body))
        return _bad_request(f"Unknown action: {action}")
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, open_world=True)
async def manage_conversions(
    action: Literal["create_pixel", "create_api_key", "set_event_settings"],
    name: str | None = None,
    client_type: Literal["web"] = "web",
    event_type: str | None = None,
    custom_event_name: str | None = None,
    attribution_window_days: int | None = None,
    source_ids: Any = None,
) -> str:
    """Change conversion setup. For reads use get_conversions.

    Actions:
    - create_pixel: POST /conversions/pixels. Requires name.
    - create_api_key: POST /conversions/api_keys. Requires name.
    - set_event_settings: POST /conversions/event_settings. Requires name,
      event_type, attribution_window_days, and source_ids.
    """
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if action == "create_pixel":
            if name_err := _validate_non_empty("name", name, minimum=3, maximum=1000):
                return name_err
            return _ok(await client.post("/conversions/pixels", json={"name": name, "client_type": client_type}))
        if action == "create_api_key":
            if name_err := _validate_non_empty("name", name, minimum=3, maximum=1000):
                return name_err
            return _ok(await client.post("/conversions/api_keys", json={"name": name}))
        if action == "set_event_settings":
            if name_err := _validate_non_empty("name", name, minimum=1, maximum=1000):
                return name_err
            if event_err := _validate_non_empty("event_type", event_type, minimum=1, maximum=100):
                return event_err
            if event_type not in _SUPPORTED_EVENT_DATA_TYPES:
                return _bad_request(f"event_type must be one of {', '.join(sorted(_SUPPORTED_EVENT_DATA_TYPES))}.")
            if event_type == "custom":
                if custom_err := _validate_custom_event_name(custom_event_name, "custom_event_name"):
                    return custom_err
            elif custom_event_name is not None:
                if custom_err := _validate_custom_event_name(custom_event_name, "custom_event_name"):
                    return custom_err
            if attribution_window_days is None or attribution_window_days < 1:
                return _bad_request("attribution_window_days must be at least 1.")
            ids, ids_err = _source_ids_payload(source_ids)
            if ids_err:
                return ids_err
            body: dict[str, Any] = {
                "name": name,
                "event_type": event_type,
                "attribution_window_days": attribution_window_days,
                "source_ids": ids,
            }
            if custom_event_name:
                body["custom_event_name"] = custom_event_name
            return _ok(await client.post("/conversions/event_settings", json=body))
        return _bad_request(f"Unknown action: {action}")
    except OpenAIAdsAPIError as e:
        return _err(e)


def _validate_custom_event_name(value: Any, name: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return _bad_request(f"{name} is required when event type is custom.")
    normalized = value.strip()
    if not _CUSTOM_EVENT_NAME_RE.match(normalized):
        return _bad_request(f"{name} must use lowercase letters, numbers, underscores, or dashes and be 1-64 characters.")
    if normalized in _BUILT_IN_EVENT_NAMES:
        return _bad_request(f"{name} must not reuse a built-in event name.")
    return None


def _validate_user_data(user: Any, index: int) -> str | None:
    if user is None:
        return None
    if not isinstance(user, dict):
        return _bad_request(f"events[{index}].user must be an object.")
    for key, value in user.items():
        lowered = key.lower()
        if "phone" in lowered:
            return _bad_request(f"events[{index}].user must not include phone numbers or phone hashes.")
        if key == "email":
            return _bad_request(f"events[{index}].user must not include raw email addresses. Send email_sha256.")
        if key != "external_id_sha256" and "external" in lowered:
            return _bad_request(f"events[{index}].user must not include raw external IDs. Send external_id_sha256.")
        if key not in _USER_FIELDS:
            return _bad_request(f"events[{index}].user contains unsupported field '{key}'.")
        if key in {"email_sha256", "external_id_sha256"}:
            if not isinstance(value, str) or _EMAIL_RE.match(value) or not _HASH_RE.match(value):
                return _bad_request(f"events[{index}].user.{key} must be a lowercase 64-character SHA-256 hex hash.")
        elif key == "country":
            if not isinstance(value, str) or not re.match(r"^[A-Za-z]{2}$", value):
                return _bad_request(f"events[{index}].user.country must be a two-letter ISO country code.")
        elif key == "city":
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                return _bad_request(f"events[{index}].user.city must be a non-empty string up to 128 characters.")
        elif key == "zip_code":
            if not isinstance(value, str) or not re.match(r"^[A-Za-z0-9 -]{1,32}$", value):
                return _bad_request(f"events[{index}].user.zip_code must be 1-32 letters, numbers, spaces, or hyphens.")
        elif key == "ip_address":
            if not isinstance(value, str):
                return _bad_request(f"events[{index}].user.ip_address must be a valid IPv4 or IPv6 address.")
            try:
                ip_address(value)
            except ValueError:
                return _bad_request(f"events[{index}].user.ip_address must be a valid IPv4 or IPv6 address.")
        elif key == "user_agent" and (not isinstance(value, str) or not value.strip()):
            return _bad_request(f"events[{index}].user.user_agent must be a non-empty string.")
        elif key == "obref" and (not isinstance(value, str) or not value.strip()):
            return _bad_request(f"events[{index}].user.obref must be a non-empty opaque browser reference.")
    return None


def _validate_event_data(event_type: str, data: Any, index: int) -> str | None:
    if not isinstance(data, dict):
        return _bad_request(f"events[{index}].data is required and must be an object.")
    expected_type = _SUPPORTED_EVENT_DATA_TYPES.get(event_type)
    if expected_type is None:
        return _bad_request(f"events[{index}].type must be one of {', '.join(sorted(_SUPPORTED_EVENT_DATA_TYPES))}.")
    if data.get("type") != expected_type:
        return _bad_request(f"events[{index}].data.type must be {expected_type} for {event_type}.")
    allowed_fields = _EVENT_DATA_FIELDS[expected_type]
    for key in data:
        if key not in allowed_fields:
            return _bad_request(f"events[{index}].data contains unsupported field '{key}'.")
    if "amount" in data and not isinstance(data["amount"], int):
        return _bad_request(f"events[{index}].data.amount must be an integer minor-unit value.")
    if "amount" in data and (not isinstance(data.get("currency"), str) or not re.match(r"^[A-Z]{3}$", data["currency"])):
        return _bad_request(f"events[{index}].data.currency is required as a 3-letter code when amount is present.")
    if "contents" in data:
        if not isinstance(data["contents"], list):
            return _bad_request(f"events[{index}].data.contents must be a list.")
        for content_index, content in enumerate(data["contents"]):
            if not isinstance(content, dict):
                return _bad_request(f"events[{index}].data.contents[{content_index}] must be an object.")
            for key in content:
                if key not in _CONTENT_FIELDS:
                    return _bad_request(f"events[{index}].data.contents[{content_index}] contains unsupported field '{key}'.")
            if "quantity" in content and not isinstance(content["quantity"], int):
                return _bad_request(f"events[{index}].data.contents[{content_index}].quantity must be an integer.")
            if "amount" in content and not isinstance(content["amount"], int):
                return _bad_request(f"events[{index}].data.contents[{content_index}].amount must be an integer minor-unit value.")
            if "amount" in content and "currency" not in data and (
                not isinstance(content.get("currency"), str) or not re.match(r"^[A-Z]{3}$", content["currency"])
            ):
                return _bad_request(f"events[{index}].data.contents[{content_index}].currency is required when item amount has no event-level currency.")
    return None


def _validate_conversion_events(events: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    parsed, err = _coerce_list(events, "events")
    if err:
        return None, err
    if not parsed:
        return None, _bad_request("events must include at least one event.")
    if len(parsed) > 1000:
        return None, _bad_request("send_conversions accepts at most 1000 events per call.")
    earliest, latest = _conversion_time_bounds_ms()
    out: list[dict[str, Any]] = []
    for index, event in enumerate(parsed):
        if not isinstance(event, dict):
            return None, _bad_request(f"events[{index}] must be an object.")
        if not event.get("id"):
            return None, _bad_request(f"events[{index}].id is required.")
        if not isinstance(event.get("id"), str) or not event["id"].strip():
            return None, _bad_request(f"events[{index}].id is required.")
        if not event.get("type"):
            return None, _bad_request(f"events[{index}].type is required.")
        if not isinstance(event.get("type"), str) or not event["type"].strip():
            return None, _bad_request(f"events[{index}].type is required.")
        event_type = event["type"].strip()
        if event_type not in _SUPPORTED_EVENT_DATA_TYPES:
            return None, _bad_request(f"events[{index}].type must be one of {', '.join(sorted(_SUPPORTED_EVENT_DATA_TYPES))}.")
        if event_type == "custom":
            if custom_err := _validate_custom_event_name(event.get("custom_event_name"), f"events[{index}].custom_event_name"):
                return None, custom_err
        if data_err := _validate_event_data(event_type, event.get("data"), index):
            return None, data_err
        if user_err := _validate_user_data(event.get("user"), index):
            return None, user_err
        timestamp_ms = event.get("timestamp_ms")
        if not isinstance(timestamp_ms, int):
            return None, _bad_request(f"events[{index}].timestamp_ms must be an integer.")
        if timestamp_ms < earliest:
            return None, _bad_request("events include a timestamp older than 7 days.")
        if timestamp_ms > latest:
            return None, _bad_request("events include a timestamp more than 10 minutes in the future.")
        action_source = event.get("action_source")
        if action_source is not None and action_source not in _ACTION_SOURCES:
            return None, _bad_request(f"events[{index}].action_source must be one of {', '.join(sorted(_ACTION_SOURCES))}.")
        if action_source == "web" and not event.get("source_url"):
            return None, _bad_request("source_url is required for web conversion events.")
        if event_type in {"app_installed", "app_opened"} and action_source != "mobile_app":
            return None, _bad_request(f"{event_type} events require action_source='mobile_app'.")
        out.append(event)
    return out, None


@ads_tool(writes=True, open_world=True)
async def send_conversions(pixel_id: str, events: Any, validate_only: bool = False) -> str:
    """Send conversion events to the OpenAI conversion ingest host.

    Posts to https://bzr.openai.com/v1/events?pid=<PIXEL-ID>. Validates the
    1000-event batch cap and timestamp window before sending. Event user data
    is never logged by this MCP server.
    """
    if pixel_err := _validate_non_empty("pixel_id", pixel_id):
        return pixel_err
    parsed_events, events_err = _validate_conversion_events(events)
    if events_err:
        return events_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post_conversions(pixel_id, parsed_events or [], validate_only))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = ("get_conversions", "manage_conversions", "send_conversions", "_validate_conversion_events")

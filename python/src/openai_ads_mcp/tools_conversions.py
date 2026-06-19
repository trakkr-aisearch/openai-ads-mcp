"""Conversion management and ingest MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *

_ACTION_SOURCES = {"web", "mobile_app", "offline", "physical_store", "phone_call", "email", "other"}


def _source_ids_payload(source_ids: Any) -> tuple[list[str] | None, str | None]:
    ids, err = _coerce_string_list(source_ids, "source_ids")
    if err:
        return None, err
    if not ids:
        return None, _bad_request("source_ids must include at least one id.")
    return ids, None


@ads_tool(writes=True)
async def manage_conversions(
    action: Literal["create_pixel", "create_api_key", "get_event_settings", "set_event_settings", "get_insights"],
    name: str | None = None,
    client_type: Literal["web"] = "web",
    event_type: str | None = None,
    custom_event_name: str | None = None,
    attribution_window_days: int | None = None,
    source_ids: Any = None,
    aggregation_level: str | None = None,
    time_ranges: Any = None,
    entity_ids: Any = None,
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> str:
    """Manage conversion setup and conversion reporting.

    Actions:
    - create_pixel: POST /conversions/pixels. Requires name.
    - create_api_key: POST /conversions/api_keys. Requires name.
    - get_event_settings: GET /conversions/event_settings.
    - set_event_settings: POST /conversions/event_settings. Requires name,
      event_type, attribution_window_days, and source_ids.
    - get_insights: POST /conversions/insights. Requires aggregation_level,
      time_ranges, and entity_ids.
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
        if action == "get_event_settings":
            if limit_err := _validate_int_range("limit", limit, 1, 500):
                return limit_err
            params = _optional_params(limit=limit, after=after, before=before, order=order)
            return _ok(await client.get("/conversions/event_settings", params=params))
        if action == "set_event_settings":
            if name_err := _validate_non_empty("name", name, minimum=1, maximum=1000):
                return name_err
            if event_err := _validate_non_empty("event_type", event_type, minimum=1, maximum=100):
                return event_err
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
        if action == "get_insights":
            if level_err := _validate_non_empty("aggregation_level", aggregation_level, minimum=1, maximum=100):
                return level_err
            ranges, ranges_err = _coerce_string_list(time_ranges, "time_ranges")
            if ranges_err:
                return ranges_err
            ids, ids_err = _coerce_string_list(entity_ids, "entity_ids")
            if ids_err:
                return ids_err
            if not ranges or not ids:
                return _bad_request("time_ranges and entity_ids are required for get_insights.")
            return _ok(await client.post(
                "/conversions/insights",
                json={"aggregation_level": aggregation_level, "time_ranges": ranges, "entity_ids": ids},
            ))
        return _bad_request(f"Unknown action: {action}")
    except OpenAIAdsAPIError as e:
        return _err(e)


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
        if not event.get("type"):
            return None, _bad_request(f"events[{index}].type is required.")
        timestamp_ms = event.get("timestamp_ms")
        if not isinstance(timestamp_ms, int):
            return None, _bad_request(f"events[{index}].timestamp_ms must be an integer.")
        if timestamp_ms < earliest:
            return None, _bad_request("events include a timestamp older than 7 days.")
        if timestamp_ms > latest:
            return None, _bad_request("events include a timestamp more than 10 minutes in the future.")
        action_source = event.get("action_source")
        if action_source not in _ACTION_SOURCES:
            return None, _bad_request(f"events[{index}].action_source must be one of {', '.join(sorted(_ACTION_SOURCES))}.")
        if action_source == "web" and not event.get("source_url"):
            return None, _bad_request("source_url is required for web conversion events.")
        out.append(event)
    return out, None


@ads_tool(writes=True, open_world=True)
async def send_conversions(pixel_id: str, events: Any) -> str:
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
        return _ok(await client.post_conversions(pixel_id, parsed_events or []))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = ("manage_conversions", "send_conversions", "_validate_conversion_events")

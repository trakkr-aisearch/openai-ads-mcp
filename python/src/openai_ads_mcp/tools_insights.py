"""Insights MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *

_INSIGHT_SCOPES = {"account", "campaign", "ad_group", "ad"}
_TIME_GRANULARITIES = {"hourly", "daily", "monthly", "none"}
_SEGMENTS = {"product", "country", "device"}
_FILTER_OPERATORS = {"IN", "GREATER_THAN", "LESS_THAN"}


def _insights_path(scope: str, entity_id: str | None) -> tuple[str | None, str | None]:
    if scope == "account":
        return "/ad_account/insights", None
    if not entity_id:
        return None, _bad_request("entity_id is required for campaign, ad_group, and ad insights.")
    if scope == "campaign":
        return f"/campaigns/{entity_id}/insights", None
    if scope == "ad_group":
        return f"/ad_groups/{entity_id}/insights", None
    if scope == "ad":
        return f"/ads/{entity_id}/insights", None
    return None, _bad_request("scope must be account, campaign, ad_group, or ad.")


def _one_time_range(value: Any) -> tuple[list[str] | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, str):
        parsed, err = _coerce_json(value, "time_range")
        if err:
            return None, err
        value = parsed
    if isinstance(value, dict):
        return [json.dumps(value, separators=_COMPACT_SEPARATORS)], None
    if isinstance(value, list):
        if len(value) != 1:
            return None, _bad_request("time_range accepts one range object.")
        item = value[0]
        if isinstance(item, str):
            parsed, err = _coerce_json(item, "time_range")
            if err:
                return None, err
            item = parsed
        if not isinstance(item, dict):
            return None, _bad_request("time_range must contain an object.")
        return [json.dumps(item, separators=_COMPACT_SEPARATORS)], None
    return None, _bad_request("time_range must be an object or JSON object string.")


def _validate_filters(value: Any) -> tuple[list[str] | None, str | None]:
    encoded, err = _json_query_list(value, "filters")
    if err or encoded is None:
        return None, err
    for item in encoded:
        try:
            parsed = json.loads(item)
        except json.JSONDecodeError:
            return None, _bad_request("filters must be JSON objects.")
        if parsed.get("operator") not in _FILTER_OPERATORS:
            return None, _bad_request("filter operator must be IN, GREATER_THAN, or LESS_THAN.")
        if "field" not in parsed or "value" not in parsed:
            return None, _bad_request("Each filter must include field, operator, and value.")
    return encoded, None


def _validate_sort(value: Any) -> tuple[list[str] | None, str | None]:
    encoded, err = _json_query_list(value, "sort")
    if err or encoded is None:
        return None, err
    for item in encoded:
        try:
            parsed = json.loads(item)
        except json.JSONDecodeError:
            return None, _bad_request("sort must be JSON objects.")
        if parsed.get("direction") not in {"asc", "desc"}:
            return None, _bad_request("sort direction must be asc or desc.")
        if "field" not in parsed:
            return None, _bad_request("Each sort entry must include field and direction.")
    return encoded, None


@ads_tool()
async def get_insights(
    scope: Literal["account", "campaign", "ad_group", "ad"],
    entity_id: str | None = None,
    time_granularity: Literal["hourly", "daily", "monthly", "none"] = "daily",
    time_range: Any = None,
    segments: Any = None,
    fields: Any = None,
    filters: Any = None,
    sort: Any = None,
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
    response_format: Literal["concise", "detailed"] = "concise",
) -> str:
    """Get performance insights for account, campaign, ad group, or ad scope.

    This is the main reporting tool. It maps to the four Ads insights
    endpoints and returns impressions, clicks, spend, CTR, CPC, CPM, and
    conversions when requested by the API.

    Use scope='account' for account-wide reporting. For scope='campaign',
    'ad_group', or 'ad', pass entity_id. time_range should be one JSON object,
    for example {"unix_range":{"start":1764547200,"end":1765152000}}. filters
    and sort are lists of JSON objects. segments can be product, country, or
    device, with at most one segment per request.

    Args:
        scope: account, campaign, ad_group, or ad.
        entity_id: Required for non-account scopes.
        time_granularity: hourly, daily, monthly, or none. Default daily.
        time_range: Optional JSON object for unix_range, hour_range, or date_range.
        segments: Optional segment list: product, country, or device.
        fields: Optional list of fields, such as campaign.id or metadata.readable_time.
        filters: Optional list of JSON filter objects.
        sort: Optional list of JSON sort objects with field and direction.
        limit: Rows per page, 1-2000. Default 20.
        after: Optional cursor for forward pagination.
        before: Optional cursor for backward pagination.
        response_format: concise caps large payloads, detailed returns more rows within the context ceiling.
    """
    if scope_err := _validate_option("scope", scope, _INSIGHT_SCOPES):
        return scope_err
    if granularity_err := _validate_option("time_granularity", time_granularity, _TIME_GRANULARITIES):
        return granularity_err
    if limit_err := _validate_int_range("limit", limit, 1, 2000):
        return limit_err
    path, path_err = _insights_path(scope, entity_id)
    if path_err:
        return path_err
    time_ranges, time_err = _one_time_range(time_range)
    if time_err:
        return time_err
    segment_values, segments_err = _coerce_string_list(segments, "segments")
    if segments_err:
        return segments_err
    if segment_values:
        if len(segment_values) > 1:
            return _bad_request("segments supports at most one value.")
        if unknown := [segment for segment in segment_values if segment not in _SEGMENTS]:
            return _bad_request(f"Invalid segments: {', '.join(unknown)}.")
    field_values, fields_err = _coerce_string_list(fields, "fields")
    if fields_err:
        return fields_err
    filter_values, filters_err = _validate_filters(filters)
    if filters_err:
        return filters_err
    sort_values, sort_err = _validate_sort(sort)
    if sort_err:
        return sort_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    params = _optional_params(
        time_granularity=time_granularity,
        time_ranges=time_ranges,
        segments=segment_values,
        fields=field_values,
        filters=filter_values,
        sort=sort_values,
        limit=limit,
        after=after,
        before=before,
    )
    try:
        return _ok_sized(
            await client.get(path, params=params),
            response_format,
            follow_up="Use after or before cursors, narrow time_range, or request fewer fields.",
        )
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = ("get_insights",)

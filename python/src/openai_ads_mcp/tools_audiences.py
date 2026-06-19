"""Custom audience MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *


@ads_tool()
async def list_audiences(
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> str:
    """List custom audiences for the authenticated ad account."""
    if limit_err := _validate_int_range("limit", limit, 1, 500):
        return limit_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    params = _optional_params(limit=limit, after=after, before=before, order=order)
    try:
        return _ok(await client.get("/custom_audiences", params=params))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool()
async def get_audience(audience_id: str) -> str:
    """Get one custom audience by id."""
    if audience_err := _validate_non_empty("audience_id", audience_id):
        return audience_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.get(f"/custom_audiences/{audience_id}"))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool()
async def search_geo(query: str) -> str:
    """Search geo targets for targeting.locations.include.

    Returns standard geo and DMA entries with ids that can be passed into
    create_campaign or update_campaign via the locations argument.
    """
    if query_err := _validate_non_empty("query", query, minimum=1, maximum=200):
        return query_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.get("/geo_lookup/search", params={"q": query, "limit": 20}))
    except OpenAIAdsAPIError as e:
        return _err(e)


def _members_payload(members: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    member_list, err = _coerce_list(members, "members")
    if err:
        return None, err
    if not member_list:
        return None, _bad_request("members is required for action='create'.")
    out: list[dict[str, Any]] = []
    for member in member_list:
        if not isinstance(member, dict):
            return None, _bad_request("Each audience member must be an object.")
        identifier_type = member.get("identifier_type")
        value = member.get("value")
        if identifier_type not in {"email", "phone", "email_sha256", "phone_number_sha256"}:
            return None, _bad_request("member identifier_type must be email, phone, email_sha256, or phone_number_sha256.")
        if not isinstance(value, str) or not value:
            return None, _bad_request("Each audience member must include a non-empty value.")
        out.append({"identifier_type": identifier_type, "value": value})
    return out, None


@ads_tool(writes=True, destructive=True)
async def manage_audience(
    action: Literal["create", "upload", "archive"],
    name: str | None = None,
    description: str | None = None,
    members: Any = None,
    audience_id: str | None = None,
    file_id: str | None = None,
    identifier_type: Literal["email", "phone", "email_sha256", "phone_number_sha256"] | None = None,
    filename: str | None = None,
    mimetype: str | None = None,
    file_size: int | None = None,
) -> str:
    """Create, upload, or archive a custom audience.

    Actions:
    - create: requires name and members, where each member has identifier_type and value.
    - upload: requires name, file_id, filename, mimetype, and file_size.
    - archive: requires audience_id.
    """
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if action == "create":
            if name_err := _validate_non_empty("name", name, minimum=3, maximum=1000):
                return name_err
            parsed_members, members_err = _members_payload(members)
            if members_err:
                return members_err
            body = {"name": name, "members": parsed_members}
            if description:
                body["description"] = description
            return _ok(await client.post("/custom_audiences", json=body))
        if action == "upload":
            if name_err := _validate_non_empty("name", name, minimum=3, maximum=1000):
                return name_err
            for field_name, value in {"file_id": file_id, "filename": filename, "mimetype": mimetype}.items():
                if field_err := _validate_non_empty(field_name, value):
                    return field_err
            if file_size is None or file_size < 1:
                return _bad_request("file_size must be at least 1.")
            body: dict[str, Any] = {
                "name": name,
                "file_id": file_id,
                "filename": filename,
                "mimetype": mimetype,
                "file_size": file_size,
            }
            if description:
                body["description"] = description
            if identifier_type:
                body["identifier_type"] = identifier_type
            return _ok(await client.post("/custom_audiences/upload", json=body))
        if action == "archive":
            if audience_err := _validate_non_empty("audience_id", audience_id):
                return audience_err
            return _ok(await client.post(f"/custom_audiences/{audience_id}/archive"))
        return _bad_request(f"Unknown action: {action}")
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = ("list_audiences", "get_audience", "search_geo", "manage_audience")

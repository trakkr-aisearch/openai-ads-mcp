"""Custom audience MCP tools for OpenAI Ads."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from ._core import *

_AUDIENCE_IDENTIFIER_TYPES = {"email", "phone", "email_sha256", "phone_number_sha256", "gaid"}


@ads_tool(open_world=True)
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


@ads_tool(open_world=True)
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


@ads_tool(open_world=True)
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


async def _upload_audience_file(
    client: OpenAIAdsClient,
    file_path: str | None,
    file_content_base64: str | None,
    filename: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """POST /uploads (purpose=custom_audience) and return the file fields for POST /custom_audiences."""
    purpose = {"purpose": "custom_audience"}
    if file_content_base64:
        if filename_err := _validate_non_empty("filename", filename, maximum=255):
            return None, filename_err
        content, content_err = _decode_base64(file_content_base64, "file_content_base64")
        if content_err:
            return None, content_err
        name = filename.strip()
        uploaded = await client.upload_bytes("/uploads", name, content, data=purpose)
        size = len(content)
    else:
        path = Path(file_path or "").expanduser()
        if not path.exists() or not path.is_file():
            return None, _bad_request("file_path must point to an existing file.")
        name = path.name
        size = path.stat().st_size
        uploaded = await client.upload_file("/uploads", str(path), data=purpose)
    file_id = uploaded.get("file_id")
    if not isinstance(file_id, str) or not file_id:
        return None, _bad_request("POST /uploads did not return a file_id.")
    return {"file_id": file_id, "filename": name, "file_size": size}, None


@ads_tool(writes=True, destructive=True, open_world=True)
async def manage_audience(
    action: Literal["upload", "archive"],
    name: str | None = None,
    description: str | None = None,
    audience_id: str | None = None,
    file_id: str | None = None,
    file_path: str | None = None,
    file_content_base64: str | None = None,
    identifier_type: Literal["email", "phone", "email_sha256", "phone_number_sha256", "gaid"] | None = None,
    filename: str | None = None,
    mimetype: str | None = None,
    file_size: int | None = None,
) -> str:
    """Create a custom audience from a customer list file, or archive one.

    Actions:
    - upload: creates an audience from a customer list file. Requires name,
      identifier_type, and exactly one of file_id (from an earlier upload),
      file_content_base64 with filename, or file_path (a file on the MCP
      server's machine; only when the server sets OPENAI_ADS_ALLOW_LOCAL_FILES=1).
      File sources are uploaded to /uploads first, then the
      audience is created from the returned file_id. mimetype defaults to a
      guess from the filename, else text/csv.
    - archive: requires audience_id.
    """
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if action == "upload":
            if name_err := _validate_non_empty("name", name, minimum=3, maximum=1000):
                return name_err
            if identifier_type is None:
                return _bad_request("identifier_type is required for action='upload'.")
            if type_err := _validate_option("identifier_type", identifier_type, _AUDIENCE_IDENTIFIER_TYPES):
                return type_err
            if sum(bool(value) for value in (file_id, file_path, file_content_base64)) != 1:
                return _bad_request("Provide exactly one of file_id, file_path, or file_content_base64.")
            if file_err := _local_file_guard(file_path, "file_content_base64 with filename, or file_id"):
                return file_err
            if file_size is not None and file_size < 1:
                return _bad_request("file_size must be at least 1.")
            if file_id:
                file_fields = _optional_params(file_id=file_id, filename=filename, file_size=file_size)
            else:
                file_fields, upload_err = await _upload_audience_file(client, file_path, file_content_base64, filename)
                if upload_err:
                    return upload_err
            if mimetype is None and file_fields.get("filename"):
                mimetype = mimetypes.guess_type(file_fields["filename"])[0] or "text/csv"
            body: dict[str, Any] = {"name": name, "identifier_type": identifier_type, **file_fields}
            if mimetype:
                body["mimetype"] = mimetype
            if description:
                body["description"] = description
            try:
                return _ok(await client.post("/custom_audiences", json=body))
            except OpenAIAdsAPIError as e:
                if not file_id:
                    e.detail = (
                        f"{e.detail} The file was already uploaded as file_id={file_fields['file_id']}; "
                        "retry with file_id instead of uploading it again."
                    )
                raise
        if action == "archive":
            if audience_err := _validate_non_empty("audience_id", audience_id):
                return audience_err
            return _ok(await client.post(f"/custom_audiences/{audience_id}/archive"))
        return _bad_request(f"Unknown action: {action}")
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = ("list_audiences", "get_audience", "search_geo", "manage_audience")

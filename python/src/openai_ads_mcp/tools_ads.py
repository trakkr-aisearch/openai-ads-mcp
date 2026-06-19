"""Ad and creative MCP tools for OpenAI Ads."""

from __future__ import annotations

from pathlib import Path

from ._core import *

_AD_STATES = {"activate", "pause", "archive"}
_AD_STATUSES = {"active", "paused", "archived"}
_CREATIVE_TYPES = {"chat_card", "product_ad_template"}


def _build_creative(
    *,
    creative_type: str | None,
    title: str | None,
    body: str | None,
    target_url: str | None = None,
    file_id: str | None = None,
    price: str | None = None,
    create: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    if creative_type is None and title is None and body is None and target_url is None and file_id is None and price is None:
        if create:
            return None, _bad_request("creative_type, title, and body are required.")
        return None, None
    if creative_type not in _CREATIVE_TYPES:
        return None, _bad_request("creative_type must be chat_card or product_ad_template.")
    if title_err := _validate_non_empty("title", title, minimum=3, maximum=50):
        return None, title_err
    if body is None:
        return None, _bad_request("body is required.")
    if len(body) > 100:
        return None, _bad_request("body must be at most 100 characters.")
    creative = {"type": creative_type, "title": title.strip(), "body": body}
    if creative_type == "chat_card":
        if target_err := _validate_non_empty("target_url", target_url, minimum=1, maximum=2048):
            return None, target_err
        if file_err := _validate_non_empty("file_id", file_id):
            return None, file_err
        creative["target_url"] = target_url
        creative["file_id"] = file_id
    if price is not None:
        if len(price) > 100:
            return None, _bad_request("price must be at most 100 characters.")
        creative["price"] = price
    return creative, None


def _build_ad_body(
    *,
    ad_group_id: str | None = None,
    name: str | None = None,
    creative_type: str | None = None,
    title: str | None = None,
    body: str | None = None,
    target_url: str | None = None,
    file_id: str | None = None,
    price: str | None = None,
    status: str | None = None,
    create: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    payload: dict[str, Any] = {}
    if create:
        if ad_group_err := _validate_non_empty("ad_group_id", ad_group_id):
            return None, ad_group_err
        payload["ad_group_id"] = ad_group_id
    if name is not None:
        if name_err := _validate_non_empty("name", name, minimum=3, maximum=1000):
            return None, name_err
        payload["name"] = name.strip()
    elif create:
        return None, _bad_request("name is required.")
    creative, creative_err = _build_creative(
        creative_type=creative_type,
        title=title,
        body=body,
        target_url=target_url,
        file_id=file_id,
        price=price,
        create=create,
    )
    if creative_err:
        return None, creative_err
    if creative is not None:
        payload["creative"] = creative
    if status is not None:
        if status not in _AD_STATUSES:
            return None, _bad_request("status must be active, paused, or archived.")
        if create and status != "paused":
            return None, _bad_request("Create tools only create paused ads. Use set_ad_state after review.")
        payload["status"] = status
    elif create:
        payload["status"] = "paused"
    if not payload:
        return None, _bad_request("Provide at least one field to update.")
    return payload, None


@ads_tool()
async def list_ads(
    ad_group_id: str,
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> str:
    """List ads in an ad group.

    Args:
        ad_group_id: Required parent ad group id.
        limit: Results per page, 1-500. Default 20.
        after: Optional cursor for forward pagination.
        before: Optional cursor for backward pagination.
        order: Sort order, asc or desc. Default desc.
    """
    if ad_group_err := _validate_non_empty("ad_group_id", ad_group_id):
        return ad_group_err
    if limit_err := _validate_int_range("limit", limit, 1, 500):
        return limit_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    params = _optional_params(ad_group_id=ad_group_id, limit=limit, after=after, before=before, order=order)
    try:
        return _ok(await client.get("/ads", params=params))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool()
async def get_ad(ad_id: str) -> str:
    """Get one ad by id, including review_status and creative metadata."""
    if ad_err := _validate_non_empty("ad_id", ad_id):
        return ad_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.get(f"/ads/{ad_id}"))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True)
async def upload_creative(image_url: str | None = None, file_path: str | None = None) -> str:
    """Upload a creative image and receive a file_id.

    Provide exactly one of image_url or file_path. image_url is sent as JSON to
    /upload. file_path is sent as multipart/form-data from the local machine.
    """
    if bool(image_url) == bool(file_path):
        return _bad_request("Provide exactly one of image_url or file_path.")
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if image_url:
            return _ok(await client.post("/upload", json={"image_url": image_url}))
        path = Path(file_path or "").expanduser()
        if not path.exists() or not path.is_file():
            return _bad_request("file_path must point to an existing file.")
        return _ok(await client.upload_file("/upload", str(path)))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True)
async def create_ad(
    ad_group_id: str,
    name: str,
    creative_type: Literal["chat_card", "product_ad_template"],
    title: str,
    body: str,
    target_url: str | None = None,
    file_id: str | None = None,
    price: str | None = None,
    status: Literal["paused", "active"] = "paused",
) -> str:
    """Create a paused ad.

    chat_card creatives require target_url and file_id. product_ad_template
    creatives use the same title/body fields and may include price.
    """
    payload, payload_err = _build_ad_body(
        ad_group_id=ad_group_id,
        name=name,
        creative_type=creative_type,
        title=title,
        body=body,
        target_url=target_url,
        file_id=file_id,
        price=price,
        status=status,
        create=True,
    )
    if payload_err:
        return payload_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post("/ads", json=payload))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True)
async def update_ad(
    ad_id: str,
    name: str | None = None,
    creative_type: Literal["chat_card", "product_ad_template"] | None = None,
    title: str | None = None,
    body: str | None = None,
    target_url: str | None = None,
    file_id: str | None = None,
    price: str | None = None,
    status: Literal["active", "paused", "archived"] | None = None,
) -> str:
    """Update ad name, creative, or status."""
    if ad_err := _validate_non_empty("ad_id", ad_id):
        return ad_err
    payload, payload_err = _build_ad_body(
        name=name,
        creative_type=creative_type,
        title=title,
        body=body,
        target_url=target_url,
        file_id=file_id,
        price=price,
        status=status,
    )
    if payload_err:
        return payload_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post(f"/ads/{ad_id}", json=payload))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, destructive=True, open_world=True)
async def set_ad_state(ad_id: str, state: Literal["activate", "pause", "archive"]) -> str:
    """Activate, pause, or archive an ad.

    Activation can start real delivery once the parent campaign and ad group are
    active, and once the ad is approved.
    """
    if ad_err := _validate_non_empty("ad_id", ad_id):
        return ad_err
    if state_err := _validate_option("state", state, _AD_STATES):
        return state_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.post(f"/ads/{ad_id}/{state}"))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = (
    "list_ads",
    "get_ad",
    "upload_creative",
    "create_ad",
    "update_ad",
    "set_ad_state",
    "_build_ad_body",
)

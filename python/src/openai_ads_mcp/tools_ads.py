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
        if activation_err := _reject_activation_status(status, "create_ad" if create else "update_ad"):
            return None, activation_err
        if create and status != "paused":
            return None, _bad_request("Create tools only create paused ads. Use set_ad_state after review.")
        payload["status"] = status
    elif create:
        payload["status"] = "paused"
    if not payload:
        return None, _bad_request("Provide at least one field to update.")
    return payload, None


@ads_tool(open_world=True)
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


@ads_tool(open_world=True)
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


@ads_tool(open_world=True)
async def get_ad_preview(ad_id: str) -> str:
    """Show how an existing ad will look in ChatGPT (temporary preview)."""
    if ad_err := _validate_non_empty("ad_id", ad_id):
        return ad_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        # A POST that only reads: write=False keeps 5xx/timeouts from saying "the write may have succeeded".
        resp = await client.post(f"/ads/{ad_id}/preview", write=False)
        data = resp.get("data") if isinstance(resp, dict) else None
        body = data[0].get("body") if isinstance(data, list) and data and isinstance(data[0], dict) else None
        return _ok({"type": "openai_ads_ad_preview", "ad_id": ad_id, "body": body})
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, open_world=True)
async def upload_creative(
    image_url: str | None = None,
    file_path: str | None = None,
    file_content_base64: str | None = None,
    filename: str | None = None,
    purpose: Literal["account_favicon"] | None = None,
) -> str:
    """Upload a creative image and receive a file_id.

    Provide exactly one of image_url, file_content_base64, or file_path.
    image_url is sent as JSON to /upload. file_content_base64 (raw image bytes,
    base64-encoded, with filename such as hero.png) is sent as
    multipart/form-data. file_path (a file on the MCP server's machine) only
    works when the server sets OPENAI_ADS_ALLOW_LOCAL_FILES=1. Set
    purpose='account_favicon' when the image is for update_ad_account_brand.
    """
    if sum(bool(value) for value in (image_url, file_path, file_content_base64)) != 1:
        return _bad_request("Provide exactly one of image_url, file_path, or file_content_base64.")
    if file_err := _local_file_guard(file_path, "file_content_base64 with filename, or image_url"):
        return file_err
    content = None
    if file_content_base64:
        if filename_err := _validate_non_empty("filename", filename, maximum=255):
            return filename_err
        content, content_err = _decode_base64(file_content_base64, "file_content_base64")
        if content_err:
            return content_err
    upload_kwargs = {"data": {"purpose": purpose}} if purpose else {}
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if image_url:
            body = {"image_url": image_url}
            if purpose:
                body["purpose"] = purpose
            return _ok(await client.post("/upload", json=body))
        if content is not None:
            return _ok(await client.upload_bytes("/upload", filename.strip(), content, **upload_kwargs))
        path = Path(file_path or "").expanduser()
        if not path.exists() or not path.is_file():
            return _bad_request("file_path must point to an existing file.")
        return _ok(await client.upload_file("/upload", str(path), **upload_kwargs))
    except OpenAIAdsAPIError as e:
        return _err(e)


_PENDING_FILE = "pending_upload"

#: What to upload before a create: ("url", image_url) or ("bytes", filename, content).
ImageUpload = tuple


def _image_source(
    file_id: str | None,
    image_url: str | None,
    image_base64: str | None = None,
    image_filename: str | None = None,
) -> tuple[str | None, ImageUpload | None, str | None]:
    """(file_id to validate with, what to upload first, error). An upload's file_id is a placeholder."""
    if sum(bool(v) for v in (file_id, image_url, image_base64)) > 1:
        return None, None, _bad_request("Pass only one of file_id, image_url or image_base64.")
    if image_url is not None:
        if not isinstance(image_url, str) or not image_url.startswith("https://"):
            return None, None, _bad_request("image_url must be a public https URL.")
        return _PENDING_FILE, ("url", image_url), None
    if image_base64 is not None:
        if name_err := _validate_non_empty("image_filename", image_filename, maximum=255):
            return None, None, name_err
        content, content_err = _decode_base64(image_base64, "image_base64")
        if content_err:
            return None, None, content_err
        return _PENDING_FILE, ("bytes", image_filename.strip(), content), None
    return file_id, None, None


async def _upload_image(client: OpenAIAdsClient, upload: ImageUpload) -> str | None:
    """Upload an image (OpenAI fetches a URL; bytes go as multipart) and return its file_id."""
    if upload[0] == "url":
        resp = await client.post("/upload", json={"image_url": upload[1]})
    else:
        resp = await client.upload_bytes("/upload", upload[1], upload[2])
    return _extract_id(resp, "file_id", "id")


@ads_tool(writes=True, open_world=True)
async def create_ad(
    ad_group_id: str,
    name: str,
    creative_type: Literal["chat_card", "product_ad_template"],
    title: str,
    body: str,
    target_url: str | None = None,
    file_id: str | None = None,
    price: str | None = None,
    status: Literal["paused"] = "paused",
    idempotency_key: str | None = None,
    image_url: str | None = None,
    image_base64: str | None = None,
    image_filename: str | None = None,
) -> str:
    """Create a paused ad.

    chat_card creatives require target_url and one image: file_id, image_url (a public https
    image), or image_base64 + image_filename (the image bytes). An image_url or image_base64 is
    uploaded only after every other field passes validation. product_ad_template
    creatives use the same title/body fields and may include price.
    target_url must be on the ad account's own website domain until the
    account's verification is approved; the API otherwise rejects it with
    "Account verification must be approved before using a different ad URL".
    idempotency_key is optional; a fresh one is generated when omitted.
    """
    file_id, image_upload, image_err = _image_source(file_id, image_url, image_base64, image_filename)
    if image_err:
        return image_err
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
    idempotency_key, idempotency_err = _validate_idempotency_key(idempotency_key)
    if idempotency_err:
        return idempotency_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if image_upload:
            uploaded = await _upload_image(client, image_upload)
            if not uploaded:
                return _bad_request("The image upload returned no file_id; nothing was created.")
            payload["creative"]["file_id"] = uploaded
        kwargs = {"json": payload}
        if idempotency_key:
            kwargs["idempotency_key"] = idempotency_key
        return _ok(await client.post("/ads", **kwargs))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(writes=True, open_world=True)
async def update_ad(
    ad_id: str,
    name: str | None = None,
    creative_type: Literal["chat_card", "product_ad_template"] | None = None,
    title: str | None = None,
    body: str | None = None,
    target_url: str | None = None,
    file_id: str | None = None,
    price: str | None = None,
    status: Literal["paused", "archived"] | None = None,
) -> str:
    """Update ad name, creative, or status.

    Creative fields can be changed one at a time: the ad is read first and the
    fields you pass are merged into its current creative, which is sent whole.
    """
    if ad_err := _validate_non_empty("ad_id", ad_id):
        return ad_err
    changes = _optional_params(
        creative_type=creative_type, title=title, body=body, target_url=target_url, file_id=file_id, price=price
    )
    payload: dict[str, Any] = {}
    if name is not None or status is not None or not changes:
        payload, payload_err = _build_ad_body(name=name, status=status)
        if payload_err:
            return payload_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        if changes:
            current = (await client.get(f"/ads/{ad_id}")).get("creative") or {}
            merged = {
                "creative_type": current.get("type"),
                "title": current.get("title"),
                "body": current.get("body"),
                "target_url": current.get("target_url"),
                "file_id": current.get("file_id"),
                "price": current.get("price"),
                **changes,
            }
            creative, creative_err = _build_creative(**merged)
            if creative_err:
                return creative_err
            if creative["type"] == "chat_card" and current.get("image_crop") and creative["file_id"] == current.get("file_id"):
                creative["image_crop"] = current["image_crop"]
            payload["creative"] = creative
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
    "get_ad_preview",
    "upload_creative",
    "create_ad",
    "update_ad",
    "set_ad_state",
    "_build_ad_body",
)

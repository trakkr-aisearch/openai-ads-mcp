"""Thin async HTTP client for the OpenAI Advertiser API."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

API_BASE_URL = "https://api.ads.openai.com/v1"
CONVERSIONS_BASE_URL = "https://bzr.openai.com/v1"

try:
    __version__ = _pkg_version("openai-ads-mcp")
except PackageNotFoundError:
    __version__ = "0+unknown"

_USER_AGENT = f"openai-ads-mcp/{__version__}"

_FRIENDLY_ERRORS: dict[int, str] = {
    401: "Invalid or expired OPENAI_ADS_API_KEY.",
    403: "Access denied. Check whether this Ads account is eligible and has permission for this endpoint.",
    404: "Resource not found. Check the id and try again.",
    429: "Rate limited by the OpenAI Ads API. Wait a moment and retry.",
}


_REASON_STATUSES = {403, 404}


def _api_reason(response: httpx.Response) -> str | None:
    """The API's own message/code from an error body, truncated; None when the body has neither."""
    try:
        body = response.json()
    except Exception:
        return response.text.strip()[:300] or None
    if not isinstance(body, dict):
        return str(body)[:300] or None
    if isinstance(body.get("error"), str):
        return body["error"][:300] or None
    error = body["error"] if isinstance(body.get("error"), dict) else body
    message = error.get("message") or error.get("detail") or body.get("detail")
    code = error.get("code")
    if not message and not code:
        return None
    reason = str(message or "")[:300]
    return f"{reason} (code {code})".strip() if code else reason


_WRITE_MAY_HAVE_SUCCEEDED = " The write may have succeeded — list or get before retrying."


def _unsafe_path_reason(path: str) -> str | None:
    """Why a request path is refused: an id must not walk to another endpoint or smuggle a query."""
    decoded = unquote(path)
    if "?" in decoded or "#" in decoded:
        return "must not contain '?' or '#'"
    if any(segment in {".", ".."} for segment in decoded.split("/")):
        return "must not contain '.' or '..' segments"
    return None


def _encode_query(params: dict | None) -> dict | None:
    """Send array query params as ``name[]=v``; the API rejects repeated plain ``name=v`` with 400."""
    if not params:
        return params
    return {
        f"{key}[]" if isinstance(value, list | tuple) and not key.endswith("[]") else key: value
        for key, value in params.items()
    }


class OpenAIAdsAPIError(Exception):
    """Raised when the OpenAI Ads API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class OpenAIAdsClient:
    """Async wrapper around the OpenAI Advertiser API."""

    def __init__(self, api_key: str, base_url: str = API_BASE_URL):
        if not api_key.strip():
            raise ValueError("OPENAI_ADS_API_KEY is required.")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": _USER_AGENT,
        }
        self._client = httpx.AsyncClient(
            base_url=self._validate_base_url(base_url, "OPENAI_ADS_API_BASE_URL"),
            headers=headers,
            timeout=60.0,
            follow_redirects=False,
        )
        self._conversions_client = httpx.AsyncClient(
            base_url=self._validate_base_url(CONVERSIONS_BASE_URL, "CONVERSIONS_BASE_URL"),
            headers=headers,
            timeout=60.0,
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()
        await self._conversions_client.aclose()

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self._request(self._client, "GET", path, params=params)

    async def post(self, path: str, json: dict | None = None, idempotency_key: str | None = None, *, write: bool = True) -> dict:
        return await self._request(self._client, "POST", path, json=json, idempotency_key=idempotency_key, write=write)

    async def patch(self, path: str, json: dict | None = None) -> dict:
        return await self._request(self._client, "PATCH", path, json=json)

    async def upload_file(self, path: str, file_path: str, data: dict | None = None) -> dict:
        local_path = Path(file_path).expanduser()
        with local_path.open("rb") as handle:
            files = {"file": (local_path.name, handle)}
            return await self._request(self._client, "POST", path, files=files, data=data)

    async def upload_bytes(self, path: str, filename: str, content: bytes, data: dict | None = None) -> dict:
        files = {"file": (filename, content)}
        return await self._request(self._client, "POST", path, files=files, data=data)

    async def post_conversions(self, pixel_id: str, events: list[dict], validate_only: bool = False) -> dict:
        return await self._request(
            self._conversions_client,
            "POST",
            "/events",
            params={"pid": pixel_id},
            json={"validate_only": validate_only, "events": events},
            redact_detail=True,
        )

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        files: dict | None = None,
        data: dict | None = None,
        redact_detail: bool = False,
        idempotency_key: str | None = None,
        write: bool | None = None,
    ) -> dict:
        if reason := _unsafe_path_reason(path):
            raise OpenAIAdsAPIError(400, f"Refused to send {method} {path!r}: ids in the path {reason}. Nothing was sent.")
        if write is None:
            write = method != "GET"
        try:
            headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
            resp = await client.request(method, path.lstrip("/"), params=_encode_query(params), json=json, files=files, data=data, headers=headers)
            resp.raise_for_status()
            if not resp.content:
                return {}
            return resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            friendly = _FRIENDLY_ERRORS.get(status)
            if friendly:
                if status in _REASON_STATUSES and not redact_detail and (reason := _api_reason(exc.response)):
                    friendly = f"{friendly} — API said: {reason}"
                raise OpenAIAdsAPIError(status, friendly) from exc
            if status >= 500:
                request_id = exc.response.headers.get("x-request-id")
                message = "OpenAI Ads API is temporarily unavailable. Please try again shortly."
                if request_id:
                    message = f"{message} Request ID: {request_id}"
                if write:
                    message += _WRITE_MAY_HAVE_SUCCEEDED
                raise OpenAIAdsAPIError(status, message) from exc
            detail = f"HTTP {status}"
            if not redact_detail:
                try:
                    body = exc.response.json()
                    detail = body.get("detail") or body.get("message") or str(body)
                except Exception:
                    detail = exc.response.text or detail
            raise OpenAIAdsAPIError(status, f"API error ({status}): {detail}") from exc
        except httpx.TimeoutException as exc:
            message = "Request timed out. The OpenAI Ads API may be under heavy load."
            raise OpenAIAdsAPIError(504, message + _WRITE_MAY_HAVE_SUCCEEDED if write else message) from exc
        except httpx.RequestError as exc:
            raise OpenAIAdsAPIError(
                0,
                f"Network error contacting OpenAI Ads API: {exc.__class__.__name__}",
            ) from exc

    @staticmethod
    def _validate_base_url(base_url: str, env_name: str) -> str:
        parsed = urlparse(base_url)
        if parsed.scheme.lower() != "https":
            raise ValueError(f"{env_name} must use https.")
        if not parsed.netloc:
            raise ValueError(f"{env_name} must include a hostname.")
        if parsed.username or parsed.password:
            raise ValueError(f"{env_name} must not include credentials.")
        if parsed.query or parsed.fragment:
            raise ValueError(f"{env_name} must not include query or fragment.")
        return base_url.rstrip("/")

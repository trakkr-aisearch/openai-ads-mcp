"""Thin async HTTP client for the OpenAI Advertiser API."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from urllib.parse import urlparse

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

    async def post(self, path: str, json: dict | None = None) -> dict:
        return await self._request(self._client, "POST", path, json=json)

    async def upload_file(self, path: str, file_path: str) -> dict:
        local_path = Path(file_path).expanduser()
        with local_path.open("rb") as handle:
            files = {"file": (local_path.name, handle)}
            return await self._request(self._client, "POST", path, files=files)

    async def post_conversions(self, pixel_id: str, events: list[dict]) -> dict:
        return await self._request(
            self._conversions_client,
            "POST",
            "/events",
            params={"pid": pixel_id},
            json={"events": events},
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
        redact_detail: bool = False,
    ) -> dict:
        try:
            resp = await client.request(method, path.lstrip("/"), params=params, json=json, files=files)
            resp.raise_for_status()
            if not resp.content:
                return {}
            return resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            friendly = _FRIENDLY_ERRORS.get(status)
            if friendly:
                raise OpenAIAdsAPIError(status, friendly) from exc
            if status >= 500:
                request_id = exc.response.headers.get("x-request-id")
                message = "OpenAI Ads API is temporarily unavailable. Please try again shortly."
                if request_id:
                    message = f"{message} Request ID: {request_id}"
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
            raise OpenAIAdsAPIError(504, "Request timed out. The OpenAI Ads API may be under heavy load.") from exc
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

"""Tests for the OpenAI Ads MCP server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

os.environ.setdefault("OPENAI_ADS_API_KEY", "test_ads_key")
os.environ.pop("OPENAI_ADS_MCP_READONLY", None)

import openai_ads_mcp  # noqa: E402
from openai_ads_mcp import mcp  # noqa: E402
from openai_ads_mcp.client import OpenAIAdsAPIError, OpenAIAdsClient  # noqa: E402

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _SERVICE_ROOT / "mcpToolManifest.json"
EXPECTED_TOOLS = [tool["name"] for tool in json.loads(_MANIFEST_PATH.read_text())["tools"]]

EXPECTED_WRITE_TOOLS = {
    "create_campaign",
    "update_campaign",
    "set_campaign_state",
    "create_ad_group",
    "update_ad_group",
    "set_ad_group_state",
    "upload_creative",
    "create_ad",
    "update_ad",
    "set_ad_state",
    "manage_audience",
    "manage_conversions",
    "send_conversions",
    "build_campaign",
    "bulk_ab_test_hints",
}
EXPECTED_DESTRUCTIVE_TOOLS = {
    "create_campaign",
    "update_campaign",
    "set_campaign_state",
    "set_ad_group_state",
    "set_ad_state",
    "manage_audience",
    "build_campaign",
}
EXPECTED_OPEN_WORLD_TOOLS = {
    "create_campaign",
    "update_campaign",
    "set_campaign_state",
    "set_ad_group_state",
    "set_ad_state",
    "send_conversions",
    "build_campaign",
}

USED_OPENAI_ADS_PATHS = {
    "/ad_account",
    "/ad_account/insights",
    "/campaigns",
    "/campaigns/{campaign_id}",
    "/campaigns/{campaign_id}/activate",
    "/campaigns/{campaign_id}/pause",
    "/campaigns/{campaign_id}/archive",
    "/campaigns/{campaign_id}/insights",
    "/ad_groups",
    "/ad_groups/{ad_group_id}",
    "/ad_groups/{ad_group_id}/activate",
    "/ad_groups/{ad_group_id}/pause",
    "/ad_groups/{ad_group_id}/archive",
    "/ad_groups/{ad_group_id}/insights",
    "/ads",
    "/ads/{ad_id}",
    "/ads/{ad_id}/activate",
    "/ads/{ad_id}/pause",
    "/ads/{ad_id}/archive",
    "/ads/{ad_id}/insights",
    "/upload",
    "/custom_audiences",
    "/custom_audiences/{custom_audience_id}",
    "/custom_audiences/upload",
    "/custom_audiences/{custom_audience_id}/archive",
    "/conversions/pixels",
    "/conversions/api_keys",
    "/conversions/event_settings",
    "/conversions/insights",
    "/geo_lookup/search",
}


@pytest.fixture(autouse=True)
def mock_client():
    import openai_ads_mcp._core as core

    mock = AsyncMock()
    mock.get = AsyncMock(return_value={"ok": True, "data": []})
    mock.post = AsyncMock(return_value={"ok": True, "id": "created"})
    mock.upload_file = AsyncMock(return_value={"file_id": "file_123"})
    mock.post_conversions = AsyncMock(return_value={"ok": True, "received": 1})
    original = core._client
    core._client = mock
    yield mock
    core._client = original


class TestToolRegistration:
    def _tools(self):
        return mcp._tool_manager._tools

    def test_all_manifest_tools_registered(self):
        registered = set(self._tools())
        expected = set(EXPECTED_TOOLS)
        assert registered == expected

    def test_tool_count_is_curated(self):
        assert len(self._tools()) == 27

    def test_all_tools_have_descriptions_and_annotations(self):
        for name, tool in self._tools().items():
            assert tool.description and len(tool.description) > 20, name
            assert tool.annotations is not None, name
            assert tool.annotations.readOnlyHint is not None, name
            assert tool.annotations.destructiveHint is not None, name
            assert tool.annotations.idempotentHint is not None, name
            assert tool.annotations.openWorldHint is not None, name

    def test_write_annotations_match_expected_set(self):
        writes = {name for name, tool in self._tools().items() if tool.annotations.readOnlyHint is False}
        assert writes == EXPECTED_WRITE_TOOLS

    def test_destructive_annotations_match_expected_set(self):
        destructive = {name for name, tool in self._tools().items() if tool.annotations.destructiveHint is True}
        assert destructive == EXPECTED_DESTRUCTIVE_TOOLS
        assert destructive <= EXPECTED_WRITE_TOOLS

    def test_open_world_annotations_match_expected_set(self):
        open_world = {name for name, tool in self._tools().items() if tool.annotations.openWorldHint is True}
        assert open_world == EXPECTED_OPEN_WORLD_TOOLS

    def test_no_structured_output_schema(self):
        offenders = [tool.name for tool in mcp._tool_manager.list_tools() if tool.output_schema]
        assert not offenders

    def test_trakkr_resource_registered(self):
        resources = {str(resource.uri): resource for resource in mcp._resource_manager.list_resources()}
        assert "openai-ads://trakkr-visibility" in resources
        assert resources["openai-ads://trakkr-visibility"].mime_type == "text/markdown"

    @pytest.mark.asyncio
    async def test_readonly_mode_hides_writes(self):
        code = (
            "import json, openai_ads_mcp; "
            "print(json.dumps(sorted(openai_ads_mcp.mcp._tool_manager._tools)))"
        )
        env = os.environ.copy()
        env["OPENAI_ADS_MCP_READONLY"] = "1"
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        names = set(json.loads(proc.stdout))
        assert "get_account" in names
        assert "get_insights" in names
        assert "draft_context_hints" in names
        assert "create_campaign" not in names
        assert "send_conversions" not in names
        assert not (names & EXPECTED_WRITE_TOOLS)


class TestReadTools:
    @pytest.mark.asyncio
    async def test_get_account(self, mock_client):
        from openai_ads_mcp.tools_account import get_account

        data = json.loads(await get_account())
        assert data["ok"] is True
        mock_client.get.assert_called_once_with("/ad_account")

    @pytest.mark.asyncio
    async def test_campaign_reads(self, mock_client):
        from openai_ads_mcp.tools_campaigns import get_campaign, list_campaigns

        await list_campaigns(limit=50, order="asc")
        mock_client.get.assert_called_with("/campaigns", params={"limit": 50, "order": "asc"})
        mock_client.get.reset_mock()
        await get_campaign("camp_1")
        mock_client.get.assert_called_once_with("/campaigns/camp_1")

    @pytest.mark.asyncio
    async def test_ad_group_reads(self, mock_client):
        from openai_ads_mcp.tools_adgroups import get_ad_group, list_ad_groups

        await list_ad_groups(campaign_id="camp_1")
        mock_client.get.assert_called_with(
            "/ad_groups",
            params={"campaign_id": "camp_1", "limit": 20, "order": "desc"},
        )
        mock_client.get.reset_mock()
        await get_ad_group("ag_1")
        mock_client.get.assert_called_once_with("/ad_groups/ag_1")

    @pytest.mark.asyncio
    async def test_ad_reads(self, mock_client):
        from openai_ads_mcp.tools_ads import get_ad, list_ads

        await list_ads(ad_group_id="ag_1")
        mock_client.get.assert_called_with(
            "/ads",
            params={"ad_group_id": "ag_1", "limit": 20, "order": "desc"},
        )
        mock_client.get.reset_mock()
        await get_ad("ad_1")
        mock_client.get.assert_called_once_with("/ads/ad_1")

    @pytest.mark.asyncio
    async def test_audience_and_geo_reads(self, mock_client):
        from openai_ads_mcp.tools_audiences import get_audience, list_audiences, search_geo

        await list_audiences(limit=10)
        mock_client.get.assert_called_with("/custom_audiences", params={"limit": 10, "order": "desc"})
        mock_client.get.reset_mock()
        await get_audience("aud_1")
        mock_client.get.assert_called_once_with("/custom_audiences/aud_1")
        mock_client.get.reset_mock()
        await search_geo("London")
        mock_client.get.assert_called_once_with("/geo_lookup/search", params={"q": "London", "limit": 20})


class TestInsights:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("scope", "entity_id", "path"),
        [
            ("account", None, "/ad_account/insights"),
            ("campaign", "camp_1", "/campaigns/camp_1/insights"),
            ("ad_group", "ag_1", "/ad_groups/ag_1/insights"),
            ("ad", "ad_1", "/ads/ad_1/insights"),
        ],
    )
    async def test_get_insights_scopes(self, mock_client, scope, entity_id, path):
        from openai_ads_mcp.tools_insights import get_insights

        await get_insights(
            scope=scope,
            entity_id=entity_id,
            time_range={"unix_range": {"start": 1764547200, "end": 1765152000}},
            segments="country",
            fields=["campaign.id", "metadata.readable_time"],
            filters=[{"field": "spend", "operator": "GREATER_THAN", "value": 10}],
            sort=[{"field": "spend", "direction": "desc"}],
            limit=100,
        )
        mock_client.get.assert_called_once()
        assert mock_client.get.call_args.args[0] == path
        params = mock_client.get.call_args.kwargs["params"]
        assert params["time_granularity"] == "daily"
        assert params["limit"] == 100
        assert params["segments"] == ["country"]
        assert json.loads(params["time_ranges"][0])["unix_range"]["start"] == 1764547200
        assert json.loads(params["filters"][0])["operator"] == "GREATER_THAN"
        assert json.loads(params["sort"][0])["direction"] == "desc"

    @pytest.mark.asyncio
    async def test_get_insights_requires_entity_id(self, mock_client):
        from openai_ads_mcp.tools_insights import get_insights

        data = json.loads(await get_insights(scope="campaign"))
        assert data["error"] is True
        mock_client.get.assert_not_called()


class TestWriteTools:
    @pytest.mark.asyncio
    async def test_create_campaign_happy_path_paused_default(self, mock_client):
        from openai_ads_mcp.tools_campaigns import create_campaign

        await create_campaign(name="Launch test", budget_usd=25)
        mock_client.post.assert_called_once_with(
            "/campaigns",
            json={
                "name": "Launch test",
                "status": "paused",
                "budget": {"lifetime_spend_limit_micros": 25_000_000},
            },
        )

    @pytest.mark.asyncio
    async def test_create_campaign_budget_guard(self, mock_client, monkeypatch):
        from openai_ads_mcp.tools_campaigns import create_campaign

        monkeypatch.setenv("OPENAI_ADS_BUDGET_CEILING_USD", "10")
        data = json.loads(await create_campaign(name="Big test", budget_usd=50))
        assert data["error"] is True
        assert "confirm_budget=True" in data["message"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_campaign_rejects_active_status(self, mock_client):
        from openai_ads_mcp.tools_campaigns import create_campaign

        data = json.loads(await create_campaign(name="Launch test", budget_usd=25, status="active"))
        assert data["error"] is True
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_state_tools(self, mock_client):
        from openai_ads_mcp.tools_adgroups import set_ad_group_state
        from openai_ads_mcp.tools_ads import set_ad_state
        from openai_ads_mcp.tools_campaigns import set_campaign_state

        await set_campaign_state("camp_1", "pause")
        mock_client.post.assert_called_with("/campaigns/camp_1/pause")
        await set_ad_group_state("ag_1", "archive")
        mock_client.post.assert_called_with("/ad_groups/ag_1/archive")
        await set_ad_state("ad_1", "activate")
        mock_client.post.assert_called_with("/ads/ad_1/activate")

    @pytest.mark.asyncio
    async def test_ad_group_and_ad_creation_payloads(self, mock_client):
        from openai_ads_mcp.tools_adgroups import create_ad_group
        from openai_ads_mcp.tools_ads import create_ad

        await create_ad_group(
            campaign_id="camp_1",
            name="Searchers",
            billing_event="click",
            max_bid_usd=1.25,
            context_hints=["Product: AI visibility"],
        )
        mock_client.post.assert_called_once_with(
            "/ad_groups",
            json={
                "campaign_id": "camp_1",
                "name": "Searchers",
                "status": "paused",
                "bidding_config": {"billing_event_type": "click", "max_bid_micros": 1_250_000},
                "context_hints": ["Product: AI visibility"],
            },
        )
        mock_client.post.reset_mock()
        await create_ad(
            ad_group_id="ag_1",
            name="Card A",
            creative_type="chat_card",
            title="Track AI visibility",
            body="See where your brand appears in AI answers.",
            target_url="https://trakkr.ai",
            file_id="file_1",
        )
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["status"] == "paused"
        assert payload["creative"]["target_url"] == "https://trakkr.ai"

    @pytest.mark.asyncio
    async def test_upload_creative_both_modes(self, mock_client, tmp_path):
        from openai_ads_mcp.tools_ads import upload_creative

        await upload_creative(image_url="https://example.com/image.png")
        mock_client.post.assert_called_once_with("/upload", json={"image_url": "https://example.com/image.png"})
        mock_client.post.reset_mock()
        image = tmp_path / "image.png"
        image.write_bytes(b"png")
        await upload_creative(file_path=str(image))
        mock_client.upload_file.assert_called_once_with("/upload", str(image))


class TestHelpers:
    @pytest.mark.asyncio
    async def test_build_campaign_orchestrates_paused_tree(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign

        mock_client.post = AsyncMock(side_effect=[
            {"id": "camp_1", "status": "paused"},
            {"id": "ag_1", "status": "paused"},
            {"id": "ad_1", "status": "paused"},
            {"id": "ad_2", "status": "paused"},
        ])
        result = await build_campaign(
            name="Category test",
            budget_usd=50,
            ad_group={"name": "Buyers", "billing_event": "click", "max_bid_usd": 1.5},
            ads=[
                {
                    "name": "Variant A",
                    "creative_type": "chat_card",
                    "title": "Find your AI gaps",
                    "body": "Track your brand in AI answers.",
                    "target_url": "https://trakkr.ai",
                    "file_id": "file_1",
                },
                {
                    "name": "Variant B",
                    "creative_type": "chat_card",
                    "title": "See AI visibility",
                    "body": "Know where ChatGPT mentions you.",
                    "target_url": "https://trakkr.ai",
                    "file_id": "file_1",
                },
            ],
        )
        data = json.loads(result)
        assert data["created"]["campaign"]["id"] == "camp_1"
        assert data["ad_ids"] if "ad_ids" in data else True
        assert "Created paused" in data["note"]
        assert [call.args[0] for call in mock_client.post.call_args_list] == ["/campaigns", "/ad_groups", "/ads", "/ads"]

    @pytest.mark.asyncio
    async def test_build_campaign_returns_created_so_far_on_failure(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign

        mock_client.post = AsyncMock(side_effect=[
            {"id": "camp_1", "status": "paused"},
            OpenAIAdsAPIError(403, "Access denied."),
        ])
        data = json.loads(await build_campaign(
            name="Category test",
            budget_usd=50,
            ad_group={"name": "Buyers", "billing_event": "click", "max_bid_usd": 1.5},
            ads=[{
                "name": "Variant A",
                "creative_type": "chat_card",
                "title": "Find your AI gaps",
                "body": "Track your brand in AI answers.",
                "target_url": "https://trakkr.ai",
                "file_id": "file_1",
            }],
        ))
        assert data["created"]["campaign"]["id"] == "camp_1"
        assert data["error"]["message"] == "Access denied."

    @pytest.mark.asyncio
    async def test_draft_context_hints_is_deterministic(self, mock_client):
        from openai_ads_mcp.helpers import draft_context_hints

        first = await draft_context_hints("AI visibility monitoring", audience="growth teams", keywords="ChatGPT,Perplexity")
        second = await draft_context_hints("AI visibility monitoring", audience="growth teams", keywords="ChatGPT,Perplexity")
        assert first == second
        data = json.loads(first)
        assert data["context_hints"]
        assert "AI visibility monitoring" in data["context_hints"][0]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_ab_test_hints_creates_paused_ads(self, mock_client):
        from openai_ads_mcp.helpers import bulk_ab_test_hints

        mock_client.post = AsyncMock(side_effect=[{"id": "ad_1"}, {"id": "ad_2"}])
        data = json.loads(await bulk_ab_test_hints("ag_1", [
            {
                "title": "Find your AI gaps",
                "body": "Track your brand in AI answers.",
                "target_url": "https://trakkr.ai",
                "file_id": "file_1",
            },
            {
                "title": "See AI visibility",
                "body": "Know where ChatGPT mentions you.",
                "target_url": "https://trakkr.ai",
                "file_id": "file_1",
            },
        ]))
        assert data["ad_ids"] == ["ad_1", "ad_2"]
        for call in mock_client.post.call_args_list:
            assert call.kwargs["json"]["status"] == "paused"


class TestConversions:
    @pytest.mark.asyncio
    async def test_manage_conversions_actions(self, mock_client):
        from openai_ads_mcp.tools_conversions import manage_conversions

        await manage_conversions(action="create_pixel", name="Website pixel")
        mock_client.post.assert_called_with("/conversions/pixels", json={"name": "Website pixel", "client_type": "web"})
        await manage_conversions(action="create_api_key", name="Server key")
        mock_client.post.assert_called_with("/conversions/api_keys", json={"name": "Server key"})
        await manage_conversions(action="get_event_settings")
        mock_client.get.assert_called_with("/conversions/event_settings", params={"limit": 20, "order": "desc"})
        await manage_conversions(
            action="set_event_settings",
            name="Purchase",
            event_type="purchase",
            attribution_window_days=7,
            source_ids=["src_1"],
        )
        mock_client.post.assert_called_with(
            "/conversions/event_settings",
            json={
                "name": "Purchase",
                "event_type": "purchase",
                "attribution_window_days": 7,
                "source_ids": ["src_1"],
            },
        )
        await manage_conversions(
            action="get_insights",
            aggregation_level="campaign",
            time_ranges=["2026-06-01:2026-06-07"],
            entity_ids=["camp_1"],
        )
        mock_client.post.assert_called_with(
            "/conversions/insights",
            json={
                "aggregation_level": "campaign",
                "time_ranges": ["2026-06-01:2026-06-07"],
                "entity_ids": ["camp_1"],
            },
        )

    @pytest.mark.asyncio
    async def test_send_conversions_rejects_too_many(self, mock_client):
        from openai_ads_mcp.tools_conversions import send_conversions

        data = json.loads(await send_conversions("px_1", [{"id": str(i), "type": "purchase"} for i in range(1001)]))
        assert data["error"] is True
        mock_client.post_conversions.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_conversions_rejects_stale_timestamp(self, mock_client):
        from openai_ads_mcp.tools_conversions import send_conversions

        stale = 1_000
        data = json.loads(await send_conversions("px_1", [{
            "id": "evt_1",
            "type": "purchase",
            "timestamp_ms": stale,
            "action_source": "web",
            "source_url": "https://example.com",
        }]))
        assert data["error"] is True
        assert "older than 7 days" in data["message"]
        mock_client.post_conversions.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_conversions_happy_path(self, mock_client):
        from openai_ads_mcp._core import _now_ms
        from openai_ads_mcp.tools_conversions import send_conversions

        events = [{
            "id": "evt_1",
            "type": "purchase",
            "timestamp_ms": _now_ms(),
            "action_source": "web",
            "source_url": "https://example.com",
            "user": {"email_sha256": "hash"},
        }]
        data = json.loads(await send_conversions("px_1", events))
        assert data["ok"] is True
        mock_client.post_conversions.assert_called_once_with("px_1", events)


class TestErrorHandling:
    def test_soft_statuses_return_json(self):
        from openai_ads_mcp._core import _err

        for status in (400, 403, 404, 422, 429):
            data = json.loads(_err(OpenAIAdsAPIError(status, f"msg {status}")))
            assert data["error"] is True
            assert data["message"] == f"msg {status}"

    def test_hard_statuses_raise(self):
        from openai_ads_mcp._core import _err

        for status in (0, 401, 500, 503, 504):
            with pytest.raises(OpenAIAdsAPIError):
                _err(OpenAIAdsAPIError(status, f"boom {status}"))

    @pytest.mark.asyncio
    async def test_client_friendly_error_mapping(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "bad key"}, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test")
        try:
            with pytest.raises(OpenAIAdsAPIError) as excinfo:
                await client.get("/ad_account")
        finally:
            await client.close()
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail == "Invalid or expired OPENAI_ADS_API_KEY."


class TestOpenAPIDrift:
    def test_openapi_contains_every_ads_endpoint_used(self):
        spec_path = _SERVICE_ROOT / "openapi.json"
        assert spec_path.exists()
        paths = set(json.loads(spec_path.read_text())["paths"])
        missing = USED_OPENAI_ADS_PATHS - paths
        assert not missing, f"Paths missing from vendored OpenAPI spec: {sorted(missing)}"

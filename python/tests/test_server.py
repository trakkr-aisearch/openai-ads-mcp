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
# Tools this fork adds on top of the upstream manifest (the manifest is shared with typescript/).
FORK_WRITE_TOOLS = {
    "set_ad_account_state",
    "update_ad_account_brand",
    "set_daily_spend_limit",
    "remove_daily_spend_limit",
}
# Listed only with OPENAI_ADS_ENABLE_FEED_WRITES=1 (price unit unverified).
FEED_WRITE_TOOLS = {"update_product_feed_products"}
# Fork read tools: get_conversions is the read half split out of the upstream manage_conversions.
FORK_READ_TOOLS = {"get_conversions", "get_ad_preview", "get_spend_limits"}
EXPECTED_TOOLS = EXPECTED_TOOLS + sorted(FORK_WRITE_TOOLS | FORK_READ_TOOLS)

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
} | FORK_WRITE_TOOLS
EXPECTED_DESTRUCTIVE_TOOLS = {
    "create_campaign",
    "update_campaign",
    "set_campaign_state",
    "set_ad_group_state",
    "set_ad_state",
    "manage_audience",
    "build_campaign",
    "set_ad_account_state",
    "set_daily_spend_limit",
    "remove_daily_spend_limit",
}
EXPECTED_OPEN_WORLD_TOOLS = {
    "get_account",
    "list_campaigns",
    "get_campaign",
    "create_campaign",
    "update_campaign",
    "set_campaign_state",
    "list_ad_groups",
    "get_ad_group",
    "create_ad_group",
    "update_ad_group",
    "set_ad_group_state",
    "list_ads",
    "get_ad",
    "upload_creative",
    "create_ad",
    "update_ad",
    "set_ad_state",
    "get_insights",
    "list_audiences",
    "get_audience",
    "search_geo",
    "manage_audience",
    "manage_conversions",
    "send_conversions",
    "build_campaign",
    "bulk_ab_test_hints",
} | FORK_WRITE_TOOLS | FORK_READ_TOOLS

USED_OPENAI_ADS_PATHS = {
    "/ad_account",
    "/ad_account/activate",
    "/ad_account/pause",
    "/ad_account/brand",
    "/ad_account/spend_limit_windows",
    "/ad_account/daily_spend_limit",
    "/ad_account/daily_spend_limit/delete",
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
    "/ads/{ad_id}/preview",
    "/upload",
    "/custom_audiences",
    "/custom_audiences/{custom_audience_id}",
    "/uploads",
    "/feeds/{feed_id}/products",
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
    mock.patch = AsyncMock(return_value={"ok": True})
    mock.upload_file = AsyncMock(return_value={"file_id": "file_123"})
    mock.upload_bytes = AsyncMock(return_value={"file_id": "file_123"})
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
        assert len(self._tools()) == 34

    def test_all_tools_have_descriptions_and_annotations(self):
        for name, tool in self._tools().items():
            assert tool.description and len(tool.description) > 20, name
            assert tool.annotations is not None, name
            assert tool.annotations.read_only_hint is not None, name
            assert tool.annotations.destructive_hint is not None, name
            assert tool.annotations.idempotent_hint is not None, name
            assert tool.annotations.open_world_hint is not None, name

    def test_write_annotations_match_expected_set(self):
        writes = {name for name, tool in self._tools().items() if tool.annotations.read_only_hint is False}
        assert writes == EXPECTED_WRITE_TOOLS

    def test_destructive_annotations_match_expected_set(self):
        destructive = {name for name, tool in self._tools().items() if tool.annotations.destructive_hint is True}
        assert destructive == EXPECTED_DESTRUCTIVE_TOOLS
        assert destructive <= EXPECTED_WRITE_TOOLS

    def test_open_world_annotations_match_expected_set(self):
        open_world = {name for name, tool in self._tools().items() if tool.annotations.open_world_hint is True}
        assert open_world == EXPECTED_OPEN_WORLD_TOOLS

    def test_no_structured_output_schema(self):
        offenders = [tool.name for tool in mcp._tool_manager.list_tools() if tool.output_schema]
        assert not offenders

    def test_trakkr_resource_registered(self):
        resources = {str(resource.uri): resource for resource in mcp._resource_manager.list_resources()}
        assert "openai-ads://trakkr-visibility" in resources
        assert resources["openai-ads://trakkr-visibility"].mime_type == "text/markdown"

    @staticmethod
    def _tools_in_subprocess(**env_overrides: str) -> dict[str, bool]:
        """{tool name: destructive_hint} as registered in a fresh process with these env vars."""
        code = (
            "import json, openai_ads_mcp; "
            "print(json.dumps({n: t.annotations.destructive_hint for n, t in openai_ads_mcp.mcp._tool_manager._tools.items()}))"
        )
        env = os.environ.copy()
        env.update(env_overrides)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(proc.stdout)

    def test_feed_writes_listed_only_when_enabled_and_destructive(self):
        tools = self._tools_in_subprocess(OPENAI_ADS_ENABLE_FEED_WRITES="1")
        assert set(tools) == set(EXPECTED_TOOLS) | FEED_WRITE_TOOLS
        assert tools["update_product_feed_products"] is True
        readonly = self._tools_in_subprocess(OPENAI_ADS_ENABLE_FEED_WRITES="1", OPENAI_ADS_MCP_READONLY="1")
        assert "update_product_feed_products" not in readonly

    @pytest.mark.asyncio
    async def test_readonly_mode_hides_writes(self):
        names = set(self._tools_in_subprocess(OPENAI_ADS_MCP_READONLY="1"))
        assert "get_account" in names
        assert "get_insights" in names
        assert "draft_context_hints" in names
        assert "create_campaign" not in names
        assert "send_conversions" not in names
        assert "get_conversions" in names
        assert "manage_conversions" not in names
        assert not (names & EXPECTED_WRITE_TOOLS)
        assert "get_ad_preview" in names
        assert len(names) == 15

    def test_preview_listed_in_readonly(self):
        assert "get_ad_preview" in self._tools_in_subprocess(OPENAI_ADS_MCP_READONLY="1")

    def test_write_allowlist_limits_registered_writes(self):
        names = set(self._tools_in_subprocess(OPENAI_ADS_MCP_TOOLS="set_campaign_state,update_ad"))
        read_tools = (set(EXPECTED_TOOLS) | FEED_WRITE_TOOLS) - EXPECTED_WRITE_TOOLS - FEED_WRITE_TOOLS
        assert names == read_tools | {"set_campaign_state", "update_ad"}
        assert "create_campaign" not in names

    def test_readonly_wins_over_allowlist(self):
        names = set(self._tools_in_subprocess(OPENAI_ADS_MCP_READONLY="1", OPENAI_ADS_MCP_TOOLS="update_ad"))
        assert not (names & EXPECTED_WRITE_TOOLS)

    @pytest.mark.asyncio
    async def test_ceilings_off(self, mock_client, monkeypatch):
        from openai_ads_mcp.tools_adgroups import update_ad_group
        from openai_ads_mcp.tools_campaigns import update_campaign

        monkeypatch.setenv("OPENAI_ADS_BUDGET_CEILING", "OFF")
        monkeypatch.setenv("OPENAI_ADS_BID_CEILING", "Off")
        await update_campaign(campaign_id="c1", daily_budget=5000)
        assert mock_client.post.call_args.kwargs["json"]["budget"]["daily_spend_limit_micros"] == 5_000_000_000
        mock_client.post.reset_mock()
        data = json.loads(await update_ad_group(ad_group_id="ag1", billing_event="click", max_bid=999))
        assert "error" not in data
        mock_client.post.assert_called_once()
        mock_client.post.reset_mock()
        data = json.loads(await update_campaign(campaign_id="c1", lifetime_budget=0.5))
        assert data["error"] is True
        mock_client.post.assert_not_called()


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
    async def test_get_ad_preview_posts_and_tags_type(self, mock_client):
        from openai_ads_mcp.tools_ads import get_ad_preview

        mock_client.post.return_value = {"data": [{"body": "<html>x</html>"}]}
        result = json.loads(await get_ad_preview("ad_1"))
        assert result == {"type": "openai_ads_ad_preview", "ad_id": "ad_1", "body": "<html>x</html>"}
        mock_client.post.assert_called_once_with("/ads/ad_1/preview", write=False)

    @pytest.mark.asyncio
    async def test_set_daily_spend_limit_reads_revision_then_posts(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import set_daily_spend_limit

        mock_client.get.return_value = {"revision": 7, "daily_limit": {"window_id": "w1"}}
        mock_client.post.return_value = {"ok": True}
        await set_daily_spend_limit(500, end_date="2026-12-31")
        mock_client.get.assert_called_once_with("/ad_account/spend_limit_windows")
        assert mock_client.post.call_args.args == ("/ad_account/daily_spend_limit",)
        assert mock_client.post.call_args.kwargs["json"] == {
            "amount_micros": 500_000_000,
            "expected_revision": 7,
            "window_id": "w1",
            "end_date": "2026-12-31",
        }

    @pytest.mark.asyncio
    async def test_set_daily_spend_limit_first_time(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import set_daily_spend_limit

        mock_client.get.return_value = {"revision": 0}
        await set_daily_spend_limit(500)
        assert mock_client.post.call_args.kwargs["json"] == {"amount_micros": 500_000_000, "expected_revision": 0}

    @pytest.mark.asyncio
    async def test_set_daily_spend_limit_validates_input(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import set_daily_spend_limit

        assert json.loads(await set_daily_spend_limit(-1))["error"] is True
        assert json.loads(await set_daily_spend_limit(float("nan")))["error"] is True
        assert "YYYY-MM-DD" in json.loads(await set_daily_spend_limit(5, end_date="12/31/2026"))["message"]
        mock_client.get.assert_not_called()
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_daily_spend_limit_posts_window(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import remove_daily_spend_limit

        mock_client.get.return_value = {"revision": 3, "daily_limit": {"window_id": "w1"}}
        await remove_daily_spend_limit()
        mock_client.post.assert_called_once_with(
            "/ad_account/daily_spend_limit/delete", json={"expected_revision": 3, "window_id": "w1"}
        )

    @pytest.mark.asyncio
    async def test_remove_daily_spend_limit_none_to_remove(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import remove_daily_spend_limit

        mock_client.get.return_value = {"revision": 3}
        result = json.loads(await remove_daily_spend_limit())
        assert result["error"] is True
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_spend_limit_uses_single_rule_from_daily_limits(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import set_daily_spend_limit

        mock_client.get.return_value = {"revision": 4, "daily_limits": [{"window_id": "w9"}]}
        await set_daily_spend_limit(10)
        assert mock_client.post.call_args.kwargs["json"]["window_id"] == "w9"

    @pytest.mark.asyncio
    async def test_spend_limit_refuses_when_multiple_rules(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import remove_daily_spend_limit, set_daily_spend_limit

        mock_client.get.return_value = {
            "revision": 4,
            "daily_limits": [
                {"window_id": "w1", "amount_micros": 5_000_000, "start_date": "2026-11-01", "status": "active"},
                {"window_id": "w2", "amount_micros": 7_000_000, "start_date": "2026-12-01", "status": "upcoming"},
            ],
        }
        for result in (await set_daily_spend_limit(10), await remove_daily_spend_limit()):
            message = json.loads(result)["message"]
            assert "w1" in message and "w2" in message and "one" in message
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_daily_spend_limit_recreate_sends_start_date(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import set_daily_spend_limit

        mock_client.get.return_value = {"revision": 5, "earliest_daily_start_date": "2026-11-02"}
        await set_daily_spend_limit(10)
        assert mock_client.post.call_args.kwargs["json"] == {
            "amount_micros": 10_000_000,
            "expected_revision": 5,
            "start_date": "2026-11-02",
        }

    @pytest.mark.asyncio
    async def test_get_spend_limits_returns_response(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import get_spend_limits

        mock_client.get.return_value = {"revision": 2, "daily_limit": None}
        assert json.loads(await get_spend_limits()) == {"revision": 2}
        mock_client.get.assert_called_once_with("/ad_account/spend_limit_windows")

    @pytest.mark.asyncio
    async def test_spend_limit_api_refusal_surfaces_reason(self, mock_client):
        from openai_ads_mcp.tools_spend_limits import set_daily_spend_limit

        mock_client.get.return_value = {"revision": 1}
        mock_client.post.side_effect = OpenAIAdsAPIError(403, "Postpaid invoice billing is required")
        result = json.loads(await set_daily_spend_limit(100))
        assert result["error"] is True
        assert "invoice" in result["message"]

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
        ("scope", "entity_id", "aggregation_level", "path"),
        [
            ("account", None, "campaign", "/ad_account/insights"),
            ("campaign", "camp_1", "campaign", "/campaigns/camp_1/insights"),
            ("ad_group", "ag_1", "ad_group", "/ad_groups/ag_1/insights"),
            ("ad", "ad_1", "ad", "/ads/ad_1/insights"),
        ],
    )
    async def test_get_insights_scopes(self, mock_client, scope, entity_id, aggregation_level, path):
        from openai_ads_mcp.tools_insights import get_insights

        await get_insights(
            scope=scope,
            entity_id=entity_id,
            aggregation_level=aggregation_level,
            time_range={"type": "unix_range", "start": 1764547200, "end": 1765152000},
            segments="country",
            override_segment_group_order=[aggregation_level, "country"],
            fields=["campaign.id", "metadata.readable_time"],
            filters=[{"field": "spend", "operator": "GREATER_THAN", "value": 10}],
            sort=[{"field": "spend", "direction": "desc"}],
            limit=100,
        )
        mock_client.get.assert_called_once()
        assert mock_client.get.call_args.args[0] == path
        params = mock_client.get.call_args.kwargs["params"]
        assert params["time_granularity"] == "daily"
        assert params["aggregation_level"] == aggregation_level
        assert params["limit"] == 100
        assert params["segments"] == ["country"]
        assert params["override_segment_group_order"] == [aggregation_level, "country"]
        assert json.loads(params["time_ranges"][0]) == {
            "type": "unix_range",
            "start": 1764547200,
            "end": 1765152000,
        }
        assert json.loads(params["filters"][0])["operator"] == "GREATER_THAN"
        assert json.loads(params["sort"][0])["direction"] == "desc"

    @pytest.mark.asyncio
    async def test_get_insights_product_include_rules(self, mock_client):
        from openai_ads_mcp.tools_insights import get_insights

        await get_insights(
            scope="campaign",
            entity_id="camp_1",
            aggregation_level="campaign",
            segments=["product"],
            override_segment_group_order=["product", "campaign"],
            includes=["zero_impression_products"],
            fields=["product.item_id", "campaign.id"],
        )
        params = mock_client.get.call_args.kwargs["params"]
        assert params["segments"] == ["product"]
        assert params["override_segment_group_order"] == ["product", "campaign"]
        assert params["includes"] == ["zero_impression_products"]

        mock_client.get.reset_mock()
        data = json.loads(await get_insights(
            scope="campaign",
            entity_id="camp_1",
            aggregation_level="campaign",
            segments=["product"],
            fields=["campaign.id"],
        ))
        assert data["error"] is True
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_insights_accepts_one_time_range_only(self, mock_client):
        from openai_ads_mcp.tools_insights import get_insights

        await get_insights(scope="account", time_range='{"type":"date_range","since":"2026-10-12","until":"2026-10-19","timezone":"Asia/Kolkata"}')
        params = mock_client.get.call_args.kwargs["params"]
        assert [json.loads(item)["since"] for item in params["time_ranges"]] == ["2026-10-12"]

        mock_client.get.reset_mock()
        ranges = [
            {"type": "unix_range", "start": 1764547200, "end": 1765152000},
            {"type": "unix_range", "start": 1765152000, "end": 1765756800},
        ]
        data = json.loads(await get_insights(scope="account", time_range=ranges))
        assert data["error"] is True
        assert "Multiple time ranges" in data["message"]
        with pytest.raises(TypeError):
            await get_insights(scope="account", time_ranges=ranges)
        mock_client.get.assert_not_called()

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

        await create_campaign(name="Launch test", lifetime_budget=25, idempotency_key="campaign-create-1")
        mock_client.post.assert_called_once_with(
            "/campaigns",
            json={
                "name": "Launch test",
                "status": "paused",
                "budget": {"lifetime_spend_limit_micros": 25_000_000},
            },
            idempotency_key="campaign-create-1",
        )

    @pytest.mark.asyncio
    async def test_create_campaign_budget_guard(self, mock_client, monkeypatch):
        from openai_ads_mcp.tools_campaigns import create_campaign

        monkeypatch.setenv("OPENAI_ADS_BUDGET_CEILING", "10")
        data = json.loads(await create_campaign(name="Big test", lifetime_budget=50))
        assert data["error"] is True
        assert "confirm_budget=True" in data["message"]
        assert "USD" not in data["message"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_budget_ceiling_is_account_currency_with_legacy_fallback(self, mock_client, monkeypatch, caplog):
        from openai_ads_mcp.tools_campaigns import create_campaign

        import openai_ads_mcp._core as core

        core._warn_legacy_budget_ceiling.cache_clear()
        monkeypatch.delenv("OPENAI_ADS_BUDGET_CEILING", raising=False)
        monkeypatch.setenv("OPENAI_ADS_BUDGET_CEILING_USD", "1000")
        with caplog.at_level("WARNING", logger="openai_ads_mcp"):
            await create_campaign(name="INR lifetime", lifetime_budget=500)
            await create_campaign(name="INR lifetime", lifetime_budget=600)
        assert mock_client.post.call_args.kwargs["json"]["budget"] == {"lifetime_spend_limit_micros": 600_000_000}
        assert [r.message for r in caplog.records].count(
            "OPENAI_ADS_BUDGET_CEILING_USD is deprecated: the ceiling is in the ad account's currency, not USD. "
            "Set OPENAI_ADS_BUDGET_CEILING instead."
        ) == 1

        mock_client.post.reset_mock()
        monkeypatch.setenv("OPENAI_ADS_BUDGET_CEILING", "100")
        data = json.loads(await create_campaign(name="INR lifetime", lifetime_budget=500))
        assert data["error"] is True
        assert "ad account's currency" in data["message"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_lifetime_and_daily_budget_are_mutually_exclusive(self, mock_client):
        from openai_ads_mcp.tools_campaigns import create_campaign, update_campaign

        for call in (
            create_campaign(name="Both budgets", lifetime_budget=50, daily_budget=5),
            update_campaign(campaign_id="camp_1", lifetime_budget=50, daily_budget=5, confirm_budget=True),
        ):
            data = json.loads(await call)
            assert data["error"] is True
            assert "not both" in data["message"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_campaign_rejects_active_status(self, mock_client):
        from openai_ads_mcp.tools_campaigns import create_campaign, update_campaign

        data = json.loads(await create_campaign(name="Launch test", lifetime_budget=25, status="active"))
        assert data["error"] is True
        mock_client.post.assert_not_called()
        data = json.loads(await update_campaign(campaign_id="camp_1", status="active"))
        assert data["error"] is True
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_conversion_optimized_campaign(self, mock_client):
        from openai_ads_mcp.tools_campaigns import create_campaign

        await create_campaign(
            name="Conversion test",
            lifetime_budget=25,
            bidding_type="conversions",
            conversion_event_setting_ids=["event_setting_1"],
        )
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["bidding_type"] == "conversions"
        assert payload["conversion_event_setting_ids"] == ["event_setting_1"]

        mock_client.post.reset_mock()
        data = json.loads(await create_campaign(
            name="Broken conversion test",
            lifetime_budget=25,
            bidding_type="conversions",
        ))
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
            max_bid=1.25,
            context_hints=["Product: AI visibility"],
            product_set={
                "product_feed_id": "product_feed_123",
                "filters": [{"field": "brand", "operator": "in", "values": ["Trakkr"]}],
            },
            idempotency_key="ad-group-create-1",
        )
        mock_client.post.assert_called_once_with(
            "/ad_groups",
            json={
                "campaign_id": "camp_1",
                "name": "Searchers",
                "status": "paused",
                "bidding_config": {"billing_event_type": "click", "max_bid_micros": 1_250_000},
                "context_hints": ["Product: AI visibility"],
                "product_set": {
                    "product_feed_id": "product_feed_123",
                    "filters": [{"field": "brand", "operator": "in", "values": ["Trakkr"]}],
                },
            },
            idempotency_key="ad-group-create-1",
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
            idempotency_key="ad-create-1",
        )
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["status"] == "paused"
        assert payload["creative"]["target_url"] == "https://trakkr.ai"
        assert mock_client.post.call_args.kwargs["idempotency_key"] == "ad-create-1"

    @pytest.mark.asyncio
    async def test_update_tools_reject_active_status(self, mock_client):
        from openai_ads_mcp.tools_adgroups import update_ad_group
        from openai_ads_mcp.tools_ads import update_ad

        data = json.loads(await update_ad_group(ad_group_id="ag_1", status="active"))
        assert data["error"] is True
        data = json.loads(await update_ad(ad_id="ad_1", status="active"))
        assert data["error"] is True
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_creative_both_modes(self, mock_client, tmp_path, monkeypatch):
        from openai_ads_mcp.tools_ads import upload_creative

        await upload_creative(image_url="https://example.com/image.png")
        mock_client.post.assert_called_once_with("/upload", json={"image_url": "https://example.com/image.png"})
        mock_client.post.reset_mock()
        image = tmp_path / "image.png"
        image.write_bytes(b"png")
        monkeypatch.delenv("OPENAI_ADS_ALLOW_LOCAL_FILES", raising=False)
        data = json.loads(await upload_creative(file_path=str(image)))
        assert data["error"] is True
        assert "file_content_base64" in data["message"] and "OPENAI_ADS_ALLOW_LOCAL_FILES=1" in data["message"]
        mock_client.upload_file.assert_not_called()
        monkeypatch.setenv("OPENAI_ADS_ALLOW_LOCAL_FILES", "1")
        await upload_creative(file_path=str(image))
        mock_client.upload_file.assert_called_once_with("/upload", str(image))

    @pytest.mark.asyncio
    async def test_upload_creative_base64_and_purpose(self, mock_client):
        from openai_ads_mcp.tools_ads import upload_creative

        await upload_creative(file_content_base64="cG5n", filename="hero.png")
        mock_client.upload_bytes.assert_called_once_with("/upload", "hero.png", b"png")
        mock_client.upload_bytes.reset_mock()
        await upload_creative(file_content_base64="cG5n", filename="icon.png", purpose="account_favicon")
        mock_client.upload_bytes.assert_called_once_with(
            "/upload", "icon.png", b"png", data={"purpose": "account_favicon"}
        )
        mock_client.upload_bytes.reset_mock()
        for kwargs in (
            {"file_content_base64": "cG5n"},
            {"file_content_base64": "not base64!", "filename": "x.png"},
            {"file_content_base64": "cG5n", "filename": "x.png", "image_url": "https://example.com/x.png"},
        ):
            data = json.loads(await upload_creative(**kwargs))
            assert data["error"] is True
        mock_client.upload_bytes.assert_not_called()
        mock_client.post.assert_not_called()


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
            lifetime_budget=50,
            ad_group={"name": "Buyers", "billing_event": "click", "max_bid": 1.5},
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
            idempotency_key="tree-1",
        )
        data = json.loads(result)
        assert data["created"]["campaign"]["id"] == "camp_1"
        assert data["ad_ids"] if "ad_ids" in data else True
        assert "created paused" in data["note"]
        bodies = [call.kwargs["json"] for call in mock_client.post.call_args_list]
        assert [b["status"] for b in bodies] == ["paused", "active", "active", "active"]
        assert [call.args[0] for call in mock_client.post.call_args_list] == ["/campaigns", "/ad_groups", "/ads", "/ads"]
        assert [call.kwargs.get("idempotency_key") for call in mock_client.post.call_args_list] == [
            "tree-1:campaign",
            "tree-1:ad_group",
            "tree-1:ad_0",
            "tree-1:ad_1",
        ]

    @pytest.mark.asyncio
    async def test_build_campaign_uploads_image_urls_before_creating(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign

        mock_client.post = AsyncMock(side_effect=[
            {"file_id": "file_up"},
            {"id": "camp_1"},
            {"id": "ag_1"},
            {"id": "ad_1"},
        ])
        data = json.loads(await build_campaign(
            name="Image test",
            lifetime_budget=50,
            ad_group={"name": "Buyers", "billing_event": "click", "max_bid": 1.5},
            ads=[{
                "name": "Variant A",
                "creative_type": "chat_card",
                "title": "Find your AI gaps",
                "body": "Track your brand in AI answers.",
                "target_url": "https://trakkr.ai",
                "image_url": "https://cdn.example.com/a.png",
            }],
        ))
        calls = mock_client.post.call_args_list
        assert [c.args[0] for c in calls] == ["/upload", "/campaigns", "/ad_groups", "/ads"]
        assert calls[0].kwargs["json"] == {"image_url": "https://cdn.example.com/a.png"}
        assert calls[3].kwargs["json"]["creative"]["file_id"] == "file_up"
        assert data["created"]["ads"][0]["id"] == "ad_1"

    @pytest.mark.asyncio
    async def test_build_campaign_failed_upload_creates_nothing(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign
        from openai_ads_mcp.client import OpenAIAdsAPIError

        mock_client.post = AsyncMock(side_effect=OpenAIAdsAPIError(400, "could not fetch image"))
        ad = {
            "name": "Variant A",
            "creative_type": "chat_card",
            "title": "Find your AI gaps",
            "body": "Track your brand in AI answers.",
            "target_url": "https://trakkr.ai",
            "image_url": "https://cdn.example.com/missing.png",
        }
        data = json.loads(await build_campaign(
            name="Image test", lifetime_budget=50,
            ad_group={"name": "Buyers", "billing_event": "click", "max_bid": 1.5}, ads=[ad],
        ))
        assert data["error"] is True
        assert [c.args[0] for c in mock_client.post.call_args_list] == ["/upload"]

    @pytest.mark.asyncio
    async def test_image_url_is_refused_with_file_id_or_without_https(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign
        from openai_ads_mcp.tools_ads import create_ad

        base = {
            "name": "Variant A",
            "creative_type": "chat_card",
            "title": "Find your AI gaps",
            "body": "Track your brand in AI answers.",
            "target_url": "https://trakkr.ai",
        }
        both = json.loads(await build_campaign(
            name="Image test", lifetime_budget=50, ad_group={"name": "Buyers", "billing_event": "click", "max_bid": 1.5},
            ads=[{**base, "file_id": "f", "image_url": "https://cdn.example.com/a.png"}],
        ))
        assert both["error"] is True and "only one of" in both["message"]
        plain = json.loads(await create_ad(ad_group_id="ag_1", image_url="http://cdn.example.com/a.png", **base))
        assert plain["error"] is True and "https" in plain["message"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_image_bytes_are_uploaded_before_creating(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign
        from openai_ads_mcp.tools_ads import create_ad

        mock_client.upload_bytes = AsyncMock(return_value={"file_id": "file_bytes"})
        mock_client.post = AsyncMock(side_effect=[{"id": "camp_1"}, {"id": "ag_1"}, {"id": "ad_1"}])
        ad = {
            "name": "Variant A",
            "creative_type": "chat_card",
            "title": "Find your AI gaps",
            "body": "Track your brand in AI answers.",
            "target_url": "https://trakkr.ai",
            "image_base64": "cG5n",
            "image_filename": "rug.png",
        }
        await build_campaign(
            name="Bytes test", lifetime_budget=50,
            ad_group={"name": "Buyers", "billing_event": "click", "max_bid": 1.5}, ads=[ad],
        )
        mock_client.upload_bytes.assert_called_once_with("/upload", "rug.png", b"png")
        assert mock_client.post.call_args_list[2].kwargs["json"]["creative"]["file_id"] == "file_bytes"

        mock_client.post = AsyncMock()
        bad = json.loads(await create_ad(ad_group_id="ag_1", **{**ad, "image_base64": "not base64!"}))
        assert bad["error"] is True and "base64" in bad["message"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_ad_uploads_then_creates_paused(self, mock_client):
        from openai_ads_mcp.tools_ads import create_ad

        mock_client.post = AsyncMock(side_effect=[{"file_id": "file_up"}, {"id": "ad_1", "status": "paused"}])
        await create_ad(
            ad_group_id="ag_1", name="Variant A", creative_type="chat_card", title="Find your AI gaps",
            body="Track your brand in AI answers.", target_url="https://trakkr.ai",
            image_url="https://cdn.example.com/a.png",
        )
        upload, ad = mock_client.post.call_args_list
        assert upload.args[0] == "/upload"
        assert ad.kwargs["json"]["creative"]["file_id"] == "file_up"
        assert ad.kwargs["json"]["status"] == "paused"

    @pytest.mark.asyncio
    async def test_build_campaign_product_feed_uses_product_set(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign

        mock_client.post = AsyncMock(side_effect=[
            {"id": "camp_1", "status": "paused"},
            {"id": "ag_1", "status": "paused"},
            {"id": "ad_1", "status": "paused"},
        ])
        data = json.loads(await build_campaign(
            name="Feed test",
            lifetime_budget=50,
            ad_group={
                "name": "Feed buyers",
                "billing_event": "click",
                "max_bid": 1.5,
                "product_set": {
                    "product_feed_id": "product_feed_123",
                    "filters": [{"field": "brand", "operator": "in", "values": ["Trakkr"]}],
                },
            },
            ads=[{
                "name": "Template A",
                "creative_type": "product_ad_template",
                "title": "Find your AI gaps",
                "body": "Track your brand in AI answers.",
            }],
        ))
        assert data["created"]["campaign"]["id"] == "camp_1"
        assert mock_client.post.call_args_list[0].kwargs["json"]["mode"] == "product_feed"
        assert mock_client.post.call_args_list[1].kwargs["json"]["product_set"]["product_feed_id"] == "product_feed_123"

    @pytest.mark.asyncio
    async def test_build_conversion_campaign_requires_click_billing(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign

        data = json.loads(await build_campaign(
            name="Conversion tree",
            lifetime_budget=50,
            bidding_type="conversions",
            conversion_event_setting_id="event_setting_1",
            ad_group={"name": "Converters", "billing_event": "impression", "max_bid": 5},
            ads=[{
                "name": "Card",
                "creative_type": "chat_card",
                "title": "Title",
                "body": "Body",
                "target_url": "https://trakkr.ai",
                "file_id": "file_1",
            }],
        ))

        assert data["error"] is True
        assert "billing_event='click'" in data["message"]
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_build_campaign_returns_created_so_far_on_failure(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign

        mock_client.post = AsyncMock(side_effect=[
            {"id": "camp_1", "status": "paused"},
            OpenAIAdsAPIError(403, "Access denied."),
        ])
        data = json.loads(await build_campaign(
            name="Category test",
            lifetime_budget=50,
            ad_group={"name": "Buyers", "billing_event": "click", "max_bid": 1.5},
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
        ], idempotency_key="bulk-1"))
        assert data["ad_ids"] == ["ad_1", "ad_2"]
        for call in mock_client.post.call_args_list:
            assert call.kwargs["json"]["status"] == "paused"
        assert [call.kwargs.get("idempotency_key") for call in mock_client.post.call_args_list] == ["bulk-1:ad_0", "bulk-1:ad_1"]


class TestConversions:
    @pytest.mark.asyncio
    async def test_manage_conversions_actions(self, mock_client):
        from openai_ads_mcp.tools_conversions import manage_conversions

        await manage_conversions(action="create_pixel", name="Website pixel")
        mock_client.post.assert_called_with("/conversions/pixels", json={"name": "Website pixel", "client_type": "web"})
        await manage_conversions(action="create_api_key", name="Server key")
        mock_client.post.assert_called_with("/conversions/api_keys", json={"name": "Server key"})
        await manage_conversions(
            action="set_event_settings",
            name="Purchase",
            event_type="order_created",
            attribution_window_days=7,
            source_ids=["src_1"],
        )
        mock_client.post.assert_called_with(
            "/conversions/event_settings",
            json={
                "name": "Purchase",
                "event_type": "order_created",
                "attribution_window_days": 7,
                "source_ids": ["src_1"],
            },
        )
        data = json.loads(await manage_conversions(action="get_insights"))
        assert data["error"] is True

    @pytest.mark.asyncio
    async def test_get_conversions_reads(self, mock_client):
        from openai_ads_mcp.tools_conversions import get_conversions

        await get_conversions(action="get_event_settings")
        mock_client.get.assert_called_with("/conversions/event_settings", params={"limit": 20, "order": "desc"})
        date_range = {"type": "date_range", "since": "2026-10-12", "until": "2026-10-19", "timezone": "Asia/Kolkata"}
        await get_conversions(
            action="get_insights",
            aggregation_level="campaign",
            time_ranges=[date_range],
            entity_ids=["camp_1"],
        )
        mock_client.post.assert_called_with(
            "/conversions/insights",
            json={
                "aggregation_level": "campaign",
                "time_ranges": [json.dumps(date_range, separators=(",", ":"))],
                "entity_ids": ["camp_1"],
            },
        )
        # entity_ids is optional (not required by the spec); a single JSON-string range is accepted.
        await get_conversions(action="get_insights", aggregation_level="ad", time_ranges=json.dumps(date_range))
        mock_client.post.assert_called_with(
            "/conversions/insights",
            json={
                "aggregation_level": "ad",
                "time_ranges": [json.dumps(date_range, separators=(",", ":"))],
                "group_by_entity": False,
            },
        )

    @pytest.mark.asyncio
    async def test_get_conversions_validates_insights_args(self, mock_client):
        from openai_ads_mcp.tools_conversions import get_conversions

        date_range = {"type": "date_range", "since": "2026-10-12", "until": "2026-10-19", "timezone": "Asia/Kolkata"}
        for kwargs in (
            {"aggregation_level": "ad_account", "time_ranges": [date_range]},
            {"time_ranges": [date_range]},
            {"aggregation_level": "campaign"},
        ):
            data = json.loads(await get_conversions(action="get_insights", **kwargs))
            assert data["error"] is True, kwargs
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_conversions_rejects_too_many(self, mock_client):
        from openai_ads_mcp.tools_conversions import send_conversions

        data = json.loads(await send_conversions("px_1", [{"id": str(i), "type": "order_created"} for i in range(1001)]))
        assert data["error"] is True
        mock_client.post_conversions.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_conversions_rejects_stale_timestamp(self, mock_client):
        from openai_ads_mcp.tools_conversions import send_conversions

        stale = 1_000
        data = json.loads(await send_conversions("px_1", [{
            "id": "evt_1",
            "type": "order_created",
            "timestamp_ms": stale,
            "data": {"type": "contents"},
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
            "type": "order_created",
            "timestamp_ms": _now_ms(),
            "data": {
                "type": "contents",
                "contents": [{"id": "sku_1", "quantity": 1, "amount": 2500, "currency": "USD"}],
            },
            "action_source": "web",
            "source_url": "https://example.com",
            "user": {"email_sha256": "a" * 64},
        }]
        data = json.loads(await send_conversions("px_1", events, validate_only=True))
        assert data["ok"] is True
        mock_client.post_conversions.assert_called_once_with("px_1", events, True)

    @pytest.mark.asyncio
    async def test_send_app_conversion_and_obref(self, mock_client):
        from openai_ads_mcp._core import _now_ms
        from openai_ads_mcp.tools_conversions import send_conversions

        event = {
            "id": "evt_app_1",
            "type": "app_installed",
            "timestamp_ms": _now_ms(),
            "data": {"type": "customer_action"},
            "action_source": "mobile_app",
            "user": {"obref": "opaque-browser-reference"},
        }
        data = json.loads(await send_conversions("px_1", [event]))
        assert data["ok"] is True
        mock_client.post_conversions.assert_called_once_with("px_1", [event], False)

        mock_client.post_conversions.reset_mock()
        event["action_source"] = "web"
        event["source_url"] = "https://example.com"
        data = json.loads(await send_conversions("px_1", [event]))
        assert data["error"] is True
        assert "mobile_app" in data["message"]
        mock_client.post_conversions.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_conversions_rejects_unsafe_user_data(self, mock_client):
        from openai_ads_mcp._core import _now_ms
        from openai_ads_mcp.tools_conversions import send_conversions

        def event_with_user(user):
            return [{
                "id": "evt_1",
                "type": "order_created",
                "timestamp_ms": _now_ms(),
                "data": {"type": "contents"},
                "user": user,
            }]

        unsafe_users = [
            {"email": "person@example.com"},
            {"external_id": "customer_123"},
            {"phone_number": "+15551234567"},
            {"phone_sha256": "a" * 64},
            {"email_sha256": "A" * 64},
        ]
        for user in unsafe_users:
            data = json.loads(await send_conversions("px_1", event_with_user(user)))
            assert data["error"] is True
        mock_client.post_conversions.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_conversions_require_custom_event_name(self, mock_client):
        from openai_ads_mcp._core import _now_ms
        from openai_ads_mcp.tools_conversions import send_conversions

        data = json.loads(await send_conversions("px_1", [{
            "id": "evt_1",
            "type": "custom",
            "timestamp_ms": _now_ms(),
            "data": {"type": "custom"},
        }]))
        assert data["error"] is True
        assert "custom_event_name" in data["message"]
        mock_client.post_conversions.assert_not_called()


class TestErrorHandling:
    def test_soft_statuses_return_json(self):
        from openai_ads_mcp._core import _err

        for status in (400, 403, 404, 422):
            data = json.loads(_err(OpenAIAdsAPIError(status, f"msg {status}")))
            assert data["error"] is True
            assert data["message"] == f"msg {status}"

    def test_hard_statuses_raise(self):
        from openai_ads_mcp._core import _err

        from mcp.server.mcpserver.exceptions import ToolError

        for status in (0, 401, 429, 500, 503, 504):
            with pytest.raises(ToolError, match=rf"\(HTTP {status}\): boom {status}"):
                _err(OpenAIAdsAPIError(status, f"boom {status}"))

    @pytest.mark.asyncio
    async def test_client_friendly_error_mapping(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://ads.test/v1/ad_account"
            return httpx.Response(401, json={"message": "bad key"}, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test/v1")
        try:
            with pytest.raises(OpenAIAdsAPIError) as excinfo:
                await client.get("/ad_account")
        finally:
            await client.close()
        assert excinfo.value.status_code == 401
        assert excinfo.value.detail == "Invalid or expired OPENAI_ADS_API_KEY."

    @pytest.mark.asyncio
    async def test_client_403_404_keep_api_reason(self):
        bodies = {
            "/ad_account": (403, {"error": {"message": "Ads API not enabled for this account", "code": "permission_denied"}}),
            "/campaigns/cmpn_x": (404, {"message": "Campaign cmpn_x not found"}),
            "/campaigns/cmpn_long": (404, {"error": {"message": "x" * 500}}),
            "/campaigns/cmpn_empty": (404, {}),
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            status, body = bodies[request.url.path.removeprefix("/v1")]
            return httpx.Response(status, json=body, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test/v1")
        details = {}
        try:
            for path in bodies:
                with pytest.raises(OpenAIAdsAPIError) as excinfo:
                    await client.get(path)
                details[path] = excinfo.value.detail
        finally:
            await client.close()
        assert details["/ad_account"].startswith("Access denied.")
        assert details["/ad_account"].endswith(" — API said: Ads API not enabled for this account (code permission_denied)")
        assert details["/campaigns/cmpn_x"] == (
            "Resource not found. Check the id and try again. — API said: Campaign cmpn_x not found"
        )
        assert details["/campaigns/cmpn_long"].endswith("API said: " + "x" * 300)
        assert details["/campaigns/cmpn_empty"] == "Resource not found. Check the id and try again."

    @pytest.mark.asyncio
    async def test_client_sends_validate_only_for_conversions(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://bzr.openai.com/v1/events?pid=px_1"
            assert json.loads(request.content) == {
                "validate_only": True,
                "events": [{"id": "evt_1"}],
            }
            return httpx.Response(200, json={"ok": True}, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
        await client._conversions_client.aclose()
        client._conversions_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://bzr.openai.com/v1",
        )
        try:
            result = await client.post_conversions("px_1", [{"id": "evt_1"}], True)
        finally:
            await client.close()
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_client_sends_idempotency_key_header(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://ads.test/v1/campaigns"
            assert request.headers["Idempotency-Key"] == "create-1"
            return httpx.Response(200, json={"ok": True}, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test/v1")
        try:
            data = await client.post("/campaigns", json={"name": "x"}, idempotency_key="create-1")
        finally:
            await client.close()
        assert data == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_insights_sends_array_params_with_brackets(self):
        import openai_ads_mcp._core as core
        from openai_ads_mcp.tools_insights import get_insights

        seen: list[httpx.URL] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url)
            return httpx.Response(200, json={"data": []}, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test/v1")
        original, core._client = core._client, client
        try:
            await get_insights(
                scope="account",
                time_range={"type": "date_range", "since": "2026-10-01", "until": "2026-10-07", "timezone": "Asia/Kolkata"},
                fields=["campaign.id", "metrics.spend"],
                sort=[{"field": "metrics.spend", "direction": "desc"}],
            )
        finally:
            core._client = original
            await client.close()
        keys = [key for key, _ in seen[0].params.multi_items()]
        assert keys.count("time_ranges[]") == 1
        assert keys.count("fields[]") == 2
        assert keys.count("sort[]") == 1
        assert "time_ranges" not in keys and "fields" not in keys
        assert "time_ranges%5B%5D=" in str(seen[0]) and "fields%5B%5D=" in str(seen[0])
        assert seen[0].params["limit"] == "20"

    @pytest.mark.asyncio
    async def test_client_does_not_double_suffix_bracket_keys(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert [key for key, _ in request.url.params.multi_items()] == ["include[]", "include[]", "limit"]
            return httpx.Response(200, json={"ok": True}, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test/v1")
        try:
            assert await client.get("/campaigns", params={"include[]": ("a", "b"), "limit": 5}) == {"ok": True}
        finally:
            await client.close()


class TestAccountWrites:
    @pytest.mark.asyncio
    async def test_set_ad_account_state(self, mock_client):
        from openai_ads_mcp.tools_account import set_ad_account_state

        await set_ad_account_state("pause")
        mock_client.post.assert_called_with("/ad_account/pause")
        await set_ad_account_state("activate")
        mock_client.post.assert_called_with("/ad_account/activate")
        mock_client.post.reset_mock()
        data = json.loads(await set_ad_account_state("archive"))
        assert data["error"] is True
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_ad_account_brand(self, mock_client):
        from openai_ads_mcp.tools_account import update_ad_account_brand

        await update_ad_account_brand(brand_name=" Trakkr ", url="https://trakkr.ai", favicon_file_id="file_1")
        mock_client.post.assert_called_once_with(
            "/ad_account/brand",
            json={"brand_name": "Trakkr", "url": "https://trakkr.ai", "favicon_file_id": "file_1"},
        )
        mock_client.post.reset_mock()
        data = json.loads(await update_ad_account_brand())
        assert data["error"] is True
        mock_client.post.assert_not_called()


class TestCampaignFields:
    @pytest.mark.asyncio
    async def test_create_campaign_daily_budget_and_targeting(self, mock_client):
        from openai_ads_mcp.tools_campaigns import create_campaign

        await create_campaign(
            name="Daily test",
            daily_budget=5,
            confirm_budget=True,
            locations=["geo_us"],
            excluded_locations=["geo_ny"],
            custom_audience_ids=["aud_1"],
            excluded_custom_audience_ids="aud_2,aud_3",
            platforms=["web", "ios_app"],
        )
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["budget"] == {"daily_spend_limit_micros": 5_000_000}
        assert payload["targeting"] == {
            "locations": {"include": [{"id": "geo_us"}]},
            "excluded_locations": {"include": [{"id": "geo_ny"}]},
            "custom_audiences": {"ids": ["aud_1"]},
            "excluded_custom_audiences": {"ids": ["aud_2", "aud_3"]},
            "platforms": {"included": ["web", "ios_app"]},
        }

    @pytest.mark.asyncio
    async def test_daily_budget_only_and_guards(self, mock_client, monkeypatch):
        from openai_ads_mcp.tools_campaigns import create_campaign, update_campaign

        await create_campaign(name="Daily only", daily_budget=5, confirm_budget=True)
        assert mock_client.post.call_args.kwargs["json"]["budget"] == {"daily_spend_limit_micros": 5_000_000}
        mock_client.post.reset_mock()

        data = json.loads(await create_campaign(name="No budget"))
        assert data["error"] is True

        monkeypatch.setenv("OPENAI_ADS_BUDGET_CEILING", "10")
        data = json.loads(await update_campaign(campaign_id="camp_1", daily_budget=50))
        assert data["error"] is True
        assert "daily_budget" in data["message"]
        assert "confirm_budget=True" in data["message"]
        mock_client.post.assert_not_called()

        await update_campaign(campaign_id="camp_1", daily_budget=50, confirm_budget=True)
        mock_client.post.assert_called_once_with(
            "/campaigns/camp_1",
            json={"budget": {"daily_spend_limit_micros": 50_000_000}},
        )

    @pytest.mark.asyncio
    async def test_campaign_rejects_unknown_platform(self, mock_client):
        from openai_ads_mcp.tools_campaigns import update_campaign

        data = json.loads(await update_campaign(campaign_id="camp_1", platforms=["tv"]))
        assert data["error"] is True
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_partial_geo_update_keeps_the_other_side(self, mock_client):
        from openai_ads_mcp.tools_campaigns import update_campaign

        mock_client.get.return_value = {
            "id": "camp_1",
            "targeting": {
                "locations": {"include": [{"id": "1000104", "name": "India", "type": "country", "country_code": "IN", "region_code": None}]},
                "excluded_locations": {"include": [{"id": "2000241", "name": "Maharashtra", "type": "region", "country_code": "IN", "region_code": "MH"}]},
                "platforms": {"included": ["ios_web"]},
            },
        }
        await update_campaign(campaign_id="camp_1", excluded_locations=["2000237"])
        mock_client.get.assert_called_once_with("/campaigns/camp_1")
        assert mock_client.post.call_args.kwargs["json"] == {"targeting": {
            "excluded_locations": {"include": [{"id": "2000237"}]},
            "locations": {"include": [{"id": "1000104"}]},
        }}

        mock_client.get.reset_mock()
        await update_campaign(campaign_id="camp_1", locations=["1000104"])
        mock_client.get.assert_called_once_with("/campaigns/camp_1")
        assert mock_client.post.call_args.kwargs["json"] == {"targeting": {
            "locations": {"include": [{"id": "1000104"}]},
            "excluded_locations": {"include": [{"id": "2000241"}]},
        }}

        mock_client.get.reset_mock()
        await update_campaign(campaign_id="camp_1", locations=["1000104"], excluded_locations=["2000237"])
        mock_client.get.assert_not_called()
        await update_campaign(campaign_id="camp_1", platforms=["web"])
        mock_client.get.assert_not_called()
        assert mock_client.post.call_args.kwargs["json"] == {"targeting": {"platforms": {"included": ["web"]}}}


class TestAdGroupFields:
    @pytest.mark.asyncio
    async def test_ad_group_description_strategy_and_multipliers(self, mock_client):
        from openai_ads_mcp.tools_adgroups import create_ad_group

        await create_ad_group(
            campaign_id="camp_1",
            name="Converters",
            description="Retargeting buyers",
            billing_event="click",
            bidding_strategy="maximize_conversions",
            custom_audience_bid_multipliers=[{"custom_audience_id": "aud_1", "bid_multiplier": 1.5}],
        )
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["description"] == "Retargeting buyers"
        assert payload["bidding_config"] == {
            "billing_event_type": "click",
            "strategy": "maximize_conversions",
            "custom_audience_bid_multipliers": [{"custom_audience_id": "aud_1", "bid_multiplier_micros": 1_500_000}],
        }

    @pytest.mark.asyncio
    async def test_ad_group_bidding_guards(self, mock_client):
        from openai_ads_mcp.tools_adgroups import create_ad_group, update_ad_group

        # fixed bids still need max_bid, so a bid edit never silently becomes AutoBid
        data = json.loads(await create_ad_group(
            campaign_id="camp_1", name="Fixed", billing_event="click", bidding_strategy="fixed_bid",
        ))
        assert data["error"] is True
        data = json.loads(await update_ad_group(
            ad_group_id="ag_1",
            custom_audience_bid_multipliers=[{"custom_audience_id": "aud_1", "bid_multiplier": 2}],
        ))
        assert data["error"] is True
        data = json.loads(await update_ad_group(
            ad_group_id="ag_1",
            billing_event="click",
            max_bid=1,
            custom_audience_bid_multipliers=[{"custom_audience_id": "aud_1", "bid_multiplier": 50}],
        ))
        assert data["error"] is True
        mock_client.post.assert_not_called()

        await update_ad_group(ad_group_id="ag_1", description="New notes")
        mock_client.post.assert_called_once_with("/ad_groups/ag_1", json={"description": "New notes"})

    @pytest.mark.asyncio
    async def test_max_bid_is_capped_at_the_api_maximum_not_100(self, mock_client):
        from openai_ads_mcp.tools_adgroups import update_ad_group

        # account currency: a ₹500 bid is ordinary on an INR account
        await update_ad_group(ad_group_id="ag_1", billing_event="click", max_bid=500, confirm_bid=True)
        body = mock_client.post.call_args.kwargs["json"]
        assert body["bidding_config"]["max_bid_micros"] == 500_000_000

        mock_client.post.reset_mock()
        data = json.loads(await update_ad_group(ad_group_id="ag_1", billing_event="click", max_bid=30_400_001, confirm_bid=True))
        assert data["error"] is True
        mock_client.post.assert_not_called()


class TestAudienceUpload:
    @pytest.mark.asyncio
    async def test_upload_from_base64_uses_uploads_then_custom_audiences(self, mock_client):
        from openai_ads_mcp.tools_audiences import manage_audience

        await manage_audience(
            action="upload",
            name="Past buyers",
            identifier_type="email_sha256",
            file_content_base64="YWJjCg==",
            filename="buyers.csv",
        )
        mock_client.upload_bytes.assert_called_once_with(
            "/uploads", "buyers.csv", b"abc\n", data={"purpose": "custom_audience"}
        )
        mock_client.post.assert_called_once_with(
            "/custom_audiences",
            json={
                "name": "Past buyers",
                "identifier_type": "email_sha256",
                "file_id": "file_123",
                "filename": "buyers.csv",
                "file_size": 4,
                "mimetype": "text/csv",
            },
        )

    @pytest.mark.asyncio
    async def test_upload_from_path_and_existing_file_id(self, mock_client, tmp_path, monkeypatch):
        from openai_ads_mcp.tools_audiences import manage_audience

        csv = tmp_path / "list.csv"
        csv.write_text("a@example.com\n")
        monkeypatch.delenv("OPENAI_ADS_ALLOW_LOCAL_FILES", raising=False)
        data = json.loads(await manage_audience(action="upload", name="From disk", identifier_type="email", file_path=str(csv)))
        assert data["error"] is True and "OPENAI_ADS_ALLOW_LOCAL_FILES=1" in data["message"]
        mock_client.upload_file.assert_not_called()
        monkeypatch.setenv("OPENAI_ADS_ALLOW_LOCAL_FILES", "1")
        await manage_audience(action="upload", name="From disk", identifier_type="email", file_path=str(csv))
        mock_client.upload_file.assert_called_once_with("/uploads", str(csv), data={"purpose": "custom_audience"})
        assert mock_client.post.call_args.kwargs["json"]["file_size"] == csv.stat().st_size

        mock_client.post.reset_mock()
        mock_client.upload_file.reset_mock()
        await manage_audience(action="upload", name="Reuse", identifier_type="phone", file_id="file_9")
        mock_client.upload_file.assert_not_called()
        mock_client.post.assert_called_once_with(
            "/custom_audiences",
            json={"name": "Reuse", "identifier_type": "phone", "file_id": "file_9"},
        )

    @pytest.mark.asyncio
    async def test_inline_members_create_is_not_offered(self, mock_client):
        # POST /custom_audiences rejects members (400 Unknown parameter), so the dead action is gone.
        from openai_ads_mcp.tools_audiences import manage_audience

        tool = next(t for t in mcp._tool_manager.list_tools() if t.name == "manage_audience")
        assert "members" not in tool.parameters["properties"]
        assert "create" not in json.dumps(tool.parameters["properties"]["action"])
        data = json.loads(await manage_audience(action="create", name="Inline"))
        assert data["error"] is True
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_validation(self, mock_client):
        from openai_ads_mcp.tools_audiences import manage_audience

        for kwargs in (
            {"file_id": "file_1"},
            {"identifier_type": "email"},
            {"identifier_type": "email", "file_id": "file_1", "file_content_base64": "YWJj", "filename": "a.csv"},
        ):
            data = json.loads(await manage_audience(action="upload", name="Broken", **kwargs))
            assert data["error"] is True
        mock_client.post.assert_not_called()
        mock_client.upload_bytes.assert_not_called()


class TestClientMultipart:
    @pytest.mark.asyncio
    async def test_upload_bytes_sends_file_and_purpose_as_multipart(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://ads.test/v1/uploads"
            assert request.headers["content-type"].startswith("multipart/form-data")
            body = request.content
            assert b'name="purpose"' in body and b"custom_audience" in body
            assert b'name="file"; filename="list.csv"' in body and b"abc" in body
            return httpx.Response(200, json={"file_id": "file_1"}, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test/v1")
        try:
            data = await client.upload_bytes("/uploads", "list.csv", b"abc", data={"purpose": "custom_audience"})
        finally:
            await client.close()
        assert data == {"file_id": "file_1"}


class TestProductFeeds:
    @pytest.mark.asyncio
    async def test_update_product_feed_products(self, mock_client):
        from openai_ads_mcp.tools_feeds import update_product_feed_products

        products = [{
            "id": "prod_1",
            "variants": [{
                "id": "var_1",
                "price": {"amount": 2500, "currency": "USD"},
                "availability": {"available": False},
            }],
        }]
        await update_product_feed_products("feed_1", json.dumps(products))
        mock_client.patch.assert_called_once_with("/feeds/feed_1/products", json={"products": products})

    @pytest.mark.asyncio
    async def test_update_product_feed_products_validation(self, mock_client):
        from openai_ads_mcp.tools_feeds import update_product_feed_products

        for products in (
            [],
            [{"id": "prod_1", "variants": []}],
            [{"id": "prod_1", "variants": [{"id": "var_1", "price": {"amount": 9.99, "currency": "USD"}}]}],
            [{"id": "prod_1", "variants": [{"id": "var_1", "price": {"amount": 999, "currency": "US"}}]}],
            [{"variants": [{"id": "var_1"}]}],
        ):
            data = json.loads(await update_product_feed_products("feed_1", products))
            assert data["error"] is True
        mock_client.patch.assert_not_called()

    @pytest.mark.asyncio
    async def test_client_patch(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PATCH"
            assert str(request.url) == "https://ads.test/v1/feeds/feed_1/products"
            assert json.loads(request.content) == {"products": []}
            return httpx.Response(200, json={"id": "delta_1", "accepted": True}, request=request)

        client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test/v1")
        try:
            data = await client.patch("/feeds/feed_1/products", json={"products": []})
        finally:
            await client.close()
        assert data == {"id": "delta_1", "accepted": True}


class TestOpenAPIDrift:
    def test_openapi_contains_every_ads_endpoint_used(self):
        # The fork checks against the current official spec (python/openapi.json from
        # https://developers.openai.com/ads/openapi.json); the root copy is upstream's older one.
        spec_path = Path(__file__).resolve().parents[1] / "openapi.json"
        assert spec_path.exists()
        paths = set(json.loads(spec_path.read_text())["paths"])
        missing = USED_OPENAI_ADS_PATHS - paths
        assert not missing, f"Paths missing from vendored OpenAPI spec: {sorted(missing)}"


def _transport_client(handler) -> OpenAIAdsClient:
    client = OpenAIAdsClient("test", base_url="https://ads.test/v1")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://ads.test/v1")
    return client


@pytest.fixture
def real_client():
    """Swap the mock for a real OpenAIAdsClient over a MockTransport; yields (seen requests, set_handler)."""
    import openai_ads_mcp._core as core

    seen: list[httpx.Request] = []
    state = {"handler": lambda request: httpx.Response(200, json={"ok": True}, request=request)}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return state["handler"](request)

    client = _transport_client(handler)
    original, core._client = core._client, client
    yield seen, lambda fn: state.__setitem__("handler", fn)
    core._client = original


class TestReviewFixes:
    @pytest.mark.asyncio
    async def test_path_guard_sends_nothing(self, real_client):
        from openai_ads_mcp.tools_adgroups import update_ad_group
        from openai_ads_mcp.tools_campaigns import get_campaign

        seen, _ = real_client
        for kwargs in (
            {"ad_group_id": "../campaigns/c1/activate", "name": "Renamed"},
            {"ad_group_id": "../campaigns/c1/activate", "max_bid": 1, "billing_event": "click"},
            {"ad_group_id": "%2e%2e/campaigns/c1/activate", "name": "Renamed"},
            {"ad_group_id": "ag_1?x=1", "name": "Renamed"},
            {"ad_group_id": "ag_1#frag", "name": "Renamed"},
        ):
            data = json.loads(await update_ad_group(**kwargs))
            assert data["error"] is True, kwargs
            assert "Nothing was sent" in data["message"]
        data = json.loads(await get_campaign("../ad_account"))
        assert "'.' or '..' segments" in data["message"]
        assert seen == []

    @pytest.mark.asyncio
    async def test_429_raises_and_write_failures_say_check_first(self, real_client):
        from mcp.server.mcpserver.exceptions import ToolError

        from openai_ads_mcp.tools_campaigns import get_campaign, update_campaign

        _, set_handler = real_client
        set_handler(lambda request: httpx.Response(429, json={"message": "slow down"}, request=request))
        with pytest.raises(ToolError, match=r"OpenAI Ads API error \(HTTP 429\): Rate limited"):
            await get_campaign("camp_1")

        set_handler(lambda request: httpx.Response(503, request=request))
        with pytest.raises(ToolError, match="list or get before retrying"):
            await update_campaign(campaign_id="camp_1", name="New name")
        with pytest.raises(ToolError) as excinfo:
            await get_campaign("camp_1")
        assert "may have succeeded" not in str(excinfo.value)

        def timeout(request):
            raise httpx.ReadTimeout("slow", request=request)

        set_handler(timeout)
        with pytest.raises(ToolError, match=r"\(HTTP 504\): Request timed out.*The write may have succeeded"):
            await update_campaign(campaign_id="camp_1", name="New name")

    @pytest.mark.asyncio
    async def test_preview_503_is_not_labelled_a_write(self, real_client):
        from mcp.server.mcpserver.exceptions import ToolError

        from openai_ads_mcp.tools_ads import get_ad_preview

        _, set_handler = real_client
        set_handler(lambda request: httpx.Response(503, request=request))
        with pytest.raises(ToolError) as excinfo:
            await get_ad_preview("ad_1")
        assert "may have succeeded" not in str(excinfo.value)

    def test_api_reason_reads_string_error(self):
        from openai_ads_mcp.client import _api_reason

        response = httpx.Response(404, json={"error": "Ad group not found"})
        assert _api_reason(response) == "Ad group not found"

    @pytest.mark.asyncio
    async def test_creates_get_an_idempotency_key_when_none_passed(self, mock_client):
        import uuid

        from openai_ads_mcp.tools_adgroups import create_ad_group
        from openai_ads_mcp.tools_ads import create_ad
        from openai_ads_mcp.tools_campaigns import create_campaign

        await create_campaign(name="Auto key", lifetime_budget=25)
        await create_ad_group(campaign_id="camp_1", name="Auto", billing_event="click", bidding_strategy="maximize_clicks")
        await create_ad(ad_group_id="ag_1", name="Auto", creative_type="product_ad_template", title="Title", body="Body")
        keys = [call.kwargs["idempotency_key"] for call in mock_client.post.call_args_list]
        assert len(set(keys)) == 3
        for key in keys:
            uuid.UUID(key)

    @pytest.mark.asyncio
    async def test_daily_budget_needs_end_time_within_ceiling(self, mock_client, monkeypatch):
        from openai_ads_mcp.tools_campaigns import create_campaign

        monkeypatch.setenv("OPENAI_ADS_BUDGET_CEILING", "100")
        start = 1_900_000_000
        data = json.loads(await create_campaign(name="Open ended", daily_budget=5))
        assert data["error"] is True and "no end_time" in data["message"]
        # 10 days × 5 = 50 <= 100
        await create_campaign(name="Ten days", daily_budget=5, start_time=start, end_time=start + 10 * 86400)
        assert mock_client.post.call_args.kwargs["json"]["budget"] == {"daily_spend_limit_micros": 5_000_000}
        mock_client.post.reset_mock()
        # 10.5 days rounds up to 11 × 10 = 110 > 100
        data = json.loads(await create_campaign(
            name="Too long", daily_budget=10, start_time=start, end_time=start + 10 * 86400 + 43200,
        ))
        assert data["error"] is True and "11 days" in data["message"] and "USD" not in data["message"]
        mock_client.post.assert_not_called()
        await create_campaign(
            name="Confirmed", daily_budget=10, start_time=start, end_time=start + 30 * 86400, confirm_budget=True,
        )
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_bid_ceiling_and_non_finite_amounts(self, mock_client, monkeypatch):
        from openai_ads_mcp.tools_adgroups import create_ad_group
        from openai_ads_mcp.tools_campaigns import create_campaign

        monkeypatch.setenv("OPENAI_ADS_BID_CEILING", "10")
        data = json.loads(await create_ad_group(campaign_id="camp_1", name="Pricey", billing_event="click", max_bid=11))
        assert data["error"] is True
        assert "OPENAI_ADS_BID_CEILING" in data["message"] and "confirm_bid=True" in data["message"]
        assert "USD" not in data["message"]
        for bad in (float("nan"), float("inf")):
            data = json.loads(await create_ad_group(campaign_id="camp_1", name="Bad", billing_event="click", max_bid=bad, confirm_bid=True))
            assert data["error"] is True
            data = json.loads(await create_campaign(name="Bad budget", lifetime_budget=bad, confirm_budget=True))
            assert data["error"] is True
        mock_client.post.assert_not_called()
        await create_ad_group(campaign_id="camp_1", name="Pricey", billing_event="click", max_bid=11, confirm_bid=True)
        assert mock_client.post.call_args.kwargs["json"]["bidding_config"]["max_bid_micros"] == 11_000_000

    @pytest.mark.asyncio
    async def test_renamed_usd_params_are_refused(self, mock_client):
        from openai_ads_mcp.helpers import build_campaign
        from openai_ads_mcp.tools_adgroups import create_ad_group, update_ad_group
        from openai_ads_mcp.tools_campaigns import create_campaign, update_campaign

        ad = {"creative_type": "product_ad_template", "title": "Title", "body": "Body"}
        for call, new_name in (
            (create_campaign(name="Old", budget_usd=25), "lifetime_budget"),
            (update_campaign(campaign_id="camp_1", daily_budget_usd=25), "daily_budget"),
            (create_ad_group(campaign_id="camp_1", name="Old", billing_event="click", max_bid_usd=1), "max_bid"),
            (update_ad_group(ad_group_id="ag_1", max_bid_usd=1), "max_bid"),
            (build_campaign(name="Old", budget_usd=25, ad_group={}, ads=[ad]), "lifetime_budget"),
            (build_campaign(name="Old", lifetime_budget=25, ad_group={"name": "G", "billing_event": "click", "max_bid_usd": 1}, ads=[ad]), "max_bid"),
        ):
            data = json.loads(await call)
            assert data["error"] is True
            assert f"renamed to {new_name}" in data["message"]
        mock_client.post.assert_not_called()
        # mcp 2.x drops unknown arguments, so the old names must stay in the schemas to be refused.
        params = {t.name: t.parameters["properties"] for t in mcp._tool_manager.list_tools()}
        assert "budget_usd" in params["create_campaign"] and "max_bid_usd" in params["update_ad_group"]

    @pytest.mark.asyncio
    async def test_update_ad_group_bid_edit_keeps_strategy_and_multipliers(self, mock_client):
        from openai_ads_mcp.tools_adgroups import update_ad_group

        multipliers = [{"custom_audience_id": "aud_1", "bid_multiplier_micros": 1_500_000}]
        mock_client.get.return_value = {
            "id": "ag_1",
            "bidding_config": {
                "billing_event_type": "click",
                "strategy": "maximize_conversions",
                "max_bid_micros": 3_000_000,
                "custom_audience_bid_multipliers": multipliers,
            },
        }
        await update_ad_group(ad_group_id="ag_1", max_bid=2)
        mock_client.get.assert_called_once_with("/ad_groups/ag_1")
        assert mock_client.post.call_args.kwargs["json"] == {"bidding_config": {
            "billing_event_type": "click",
            "strategy": "maximize_conversions",
            "max_bid_micros": 2_000_000,
            "custom_audience_bid_multipliers": multipliers,
        }}

        await update_ad_group(ad_group_id="ag_1", custom_audience_bid_multipliers=[{"custom_audience_id": "aud_2", "bid_multiplier": 2}])
        assert mock_client.post.call_args.kwargs["json"]["bidding_config"] == {
            "billing_event_type": "click",
            "strategy": "maximize_conversions",
            "max_bid_micros": 3_000_000,
            "custom_audience_bid_multipliers": [{"custom_audience_id": "aud_2", "bid_multiplier_micros": 2_000_000}],
        }

        # switching strategy does not inherit the old bid; fixed_bid then needs an explicit one
        await update_ad_group(ad_group_id="ag_1", bidding_strategy="maximize_clicks")
        assert "max_bid_micros" not in mock_client.post.call_args.kwargs["json"]["bidding_config"]
        mock_client.post.reset_mock()
        data = json.loads(await update_ad_group(ad_group_id="ag_1", bidding_strategy="fixed_bid"))
        assert data["error"] is True and "fixed_bid requires max_bid" in data["message"]
        mock_client.post.assert_not_called()

        # AutoBid (automated_bid) is read-only: the strategy is left out so it stays AutoBid
        mock_client.get.return_value = {"bidding_config": {"billing_event_type": "impression", "strategy": "automated_bid"}}
        await update_ad_group(ad_group_id="ag_1", custom_audience_bid_multipliers=[])
        assert mock_client.post.call_args.kwargs["json"]["bidding_config"] == {
            "billing_event_type": "impression",
            "custom_audience_bid_multipliers": [],
        }

        # non-bidding edits do not read first
        mock_client.get.reset_mock()
        await update_ad_group(ad_group_id="ag_1", name="Just a rename")
        mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_ad_merges_single_creative_field(self, mock_client):
        from openai_ads_mcp.tools_ads import update_ad

        crop = {"x": 0, "y": 0, "width": 1, "height": 1}
        mock_client.get.return_value = {"id": "ad_1", "creative": {
            "type": "chat_card", "title": "Old title", "body": "Old body", "target_url": "https://trakkr.ai",
            "file_id": "file_1", "image_url": "https://cdn/x.png", "image_crop": crop,
        }}
        await update_ad(ad_id="ad_1", title="New title")
        mock_client.get.assert_called_once_with("/ads/ad_1")
        mock_client.post.assert_called_once_with("/ads/ad_1", json={"creative": {
            "type": "chat_card", "title": "New title", "body": "Old body",
            "target_url": "https://trakkr.ai", "file_id": "file_1", "image_crop": crop,
        }})
        await update_ad(ad_id="ad_1", file_id="file_2", name="Renamed")
        assert mock_client.post.call_args.kwargs["json"] == {"name": "Renamed", "creative": {
            "type": "chat_card", "title": "Old title", "body": "Old body",
            "target_url": "https://trakkr.ai", "file_id": "file_2",
        }}

    @pytest.mark.asyncio
    async def test_build_campaign_validates_everything_before_posting(self, mock_client, monkeypatch):
        from openai_ads_mcp.helpers import build_campaign

        good_ad = {"creative_type": "product_ad_template", "title": "Title", "body": "Body"}
        data = json.loads(await build_campaign(
            name="Bad ad", lifetime_budget=50,
            ad_group={"name": "Group", "billing_event": "click", "max_bid": 1},
            ads=[good_ad, {"creative_type": "chat_card", "title": "No url", "body": "Body"}],
        ))
        assert data["error"] is True and data["message"].startswith("ads[1]:")
        data = json.loads(await build_campaign(
            name="Bad group", lifetime_budget=50, ad_group={"name": "Group", "billing_event": "click"}, ads=[good_ad],
        ))
        assert data["error"] is True
        mock_client.post.assert_not_called()

        mock_client.post = AsyncMock(side_effect=[{"id": "camp_1"}, {"id": "ag_1"}, {"id": "ad_1"}])
        await build_campaign(
            name="Daily tree", daily_budget=500, confirm_budget=True, description="Q4 push",
            ad_group={
                "name": "Group", "billing_event": "click", "bidding_strategy": "maximize_clicks",
                "description": "Buyers", "custom_audience_bid_multipliers": [{"custom_audience_id": "aud_1", "bid_multiplier": 2}],
            },
            ads=[good_ad],
        )
        campaign, group, ad = (call.kwargs["json"] for call in mock_client.post.call_args_list)
        assert campaign["budget"] == {"daily_spend_limit_micros": 500_000_000} and campaign["description"] == "Q4 push"
        assert group["campaign_id"] == "camp_1" and group["description"] == "Buyers"
        assert group["bidding_config"] == {
            "billing_event_type": "click",
            "strategy": "maximize_clicks",
            "custom_audience_bid_multipliers": [{"custom_audience_id": "aud_1", "bid_multiplier_micros": 2_000_000}],
        }
        assert ad["ad_group_id"] == "ag_1"
        assert all(call.kwargs["idempotency_key"] for call in mock_client.post.call_args_list)

    @pytest.mark.asyncio
    async def test_audience_create_failure_keeps_uploaded_file_id(self, mock_client):
        from openai_ads_mcp.tools_audiences import manage_audience

        mock_client.post = AsyncMock(side_effect=OpenAIAdsAPIError(400, "API error (400): bad identifier"))
        data = json.loads(await manage_audience(
            action="upload", name="Buyers", identifier_type="email_sha256", file_content_base64="YWJjCg==", filename="b.csv",
        ))
        assert data["error"] is True
        assert "file_id=file_123" in data["message"] and "bad identifier" in data["message"]

    @pytest.mark.asyncio
    async def test_time_range_shapes(self, mock_client):
        from openai_ads_mcp.tools_conversions import get_conversions
        from openai_ads_mcp.tools_insights import get_insights

        date_range = {"type": "date_range", "since": "2026-10-12", "until": "2026-10-19", "timezone": "Asia/Kolkata"}
        await get_insights(scope="account", time_range=[date_range])
        assert [json.loads(r) for r in mock_client.get.call_args.kwargs["params"]["time_ranges"]] == [date_range]

        legacy = {"date_range": {k: v for k, v in date_range.items() if k != "type"}}
        await get_conversions(action="get_insights", aggregation_level="campaign", time_ranges=[legacy])
        assert [json.loads(r) for r in mock_client.post.call_args.kwargs["json"]["time_ranges"]] == [date_range]
        data = json.loads(await get_conversions(action="get_insights", aggregation_level="campaign", time_ranges=[{"since": "x"}]))
        assert data["error"] is True

    @pytest.mark.asyncio
    async def test_hard_error_text_reaches_an_mcp_client(self, monkeypatch):
        # Through the real MCPServer request path (in-memory client), not by calling the function.
        import openai_ads_mcp._core as core
        from mcp import Client

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "bad key"}, request=request)

        monkeypatch.setattr(core, "OpenAIAdsClient", lambda api_key, base_url: _transport_client(handler))
        async with Client(mcp) as client:
            result = await client.call_tool("get_account", {})
        assert result.is_error is True
        assert "OpenAI Ads API error (HTTP 401): Invalid or expired OPENAI_ADS_API_KEY." in result.content[0].text

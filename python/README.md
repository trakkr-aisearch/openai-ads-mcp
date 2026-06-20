# openai-ads-mcp

<!-- mcp-name: io.github.trakkr-aisearch/openai-ads-mcp -->

Python runtime for `openai-ads-mcp`, a typed MCP server for OpenAI's Advertiser API.

## Quick start

```bash
export OPENAI_ADS_API_KEY="..."
export OPENAI_ADS_MCP_READONLY=1
uvx openai-ads-mcp
```

Readonly mode is recommended for first connection because it hides all write tools from `tools/list`.

## Local development

```bash
cd services/openai-ads-mcp/python
python -m pip install -e .
python -m pytest -q
python -c "import openai_ads_mcp; print('ok')"
```

The full README and release notes live one directory up in the service root.

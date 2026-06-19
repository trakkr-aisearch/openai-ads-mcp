# Releasing `openai-ads-mcp`

Publishing happens from the dedicated public repository:

- `https://github.com/macklpgr/openai-ads-mcp`

Do not publish from this monorepo.

## Before the First Release

Confirm that both package names are free:

- PyPI: `openai-ads-mcp`
- npm: `openai-ads-mcp`
- npm fallback, if needed: `@trakkr/openai-ads-mcp`

The public repo holds both runtimes:

- `python/`: Python package for `uvx openai-ads-mcp`
- `typescript/`: Node package for `npx -y openai-ads-mcp`
- `openapi.json`: shared vendored OpenAI Ads API reference
- `README.md`: shared funnel and usage docs
- `.github/workflows/`: PyPI, npm, and OpenAPI drift checks

## Trusted Publishing Setup

Configure trusted publishing before pushing the first release tag.

PyPI trusted publisher:

- Repository owner: `macklpgr`
- Repository name: `openai-ads-mcp`
- Workflow file: `publish-python.yml`
- Environment: leave blank unless you add one later

npm trusted publishing:

- Package: `openai-ads-mcp` or the fallback scoped name
- Repository: `macklpgr/openai-ads-mcp`
- Workflow file: `publish-npm.yml`

No PyPI or npm tokens should be stored in GitHub.

## Source-of-Truth Model

1. Source code is edited here in `services/openai-ads-mcp`.
2. Releases happen from the dedicated public repo only.
3. The vendored OpenAPI reference is the shared `openapi.json` in the repo root.
4. Both release workflows trigger on tags matching `openai-ads-mcp-v*`.
5. A real funded OpenAI Ads account is needed to validate live writes end to end. Reads can be validated with any valid OpenAI Ads API key.

## Sync and Release Flow

1. Create or update the dedicated public repository locally.

```bash
mkdir -p "/Users/mack/Cursor/openai-ads-mcp-publish"
rsync -av --delete \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  --exclude 'node_modules' \
  --exclude 'dist' \
  "/Users/mack/Cursor/Trakkr V2/services/openai-ads-mcp/" \
  "/Users/mack/Cursor/openai-ads-mcp-publish/"
```

2. Run both test suites and the spec drift check in the dedicated repo.

```bash
cd "/Users/mack/Cursor/openai-ads-mcp-publish/python"
python -m pytest -q
python -c "import openai_ads_mcp; print('ok')"

cd "../typescript"
npm install
npm run build
npm test
npm run check:openapi
```

3. Commit and push the synced public repo.

```bash
cd "/Users/mack/Cursor/openai-ads-mcp-publish"
git add .
git commit -m "Initial openai-ads-mcp release"
git push origin main
```

4. Release both packages with the shared tag.

```bash
git tag openai-ads-mcp-v0.1.0
git push origin openai-ads-mcp-v0.1.0
```

5. Confirm release.

- GitHub Actions succeeds for Python, npm, and OpenAPI drift.
- Python package is visible at `https://pypi.org/project/openai-ads-mcp/`.
- npm package is visible at `https://www.npmjs.com/package/openai-ads-mcp`.

## Manual Smoke Test

Reads can be validated with any valid OpenAI Ads API key:

```bash
export OPENAI_ADS_API_KEY="..."
export OPENAI_ADS_MCP_READONLY=1
uvx openai-ads-mcp
npx -y openai-ads-mcp
```

Live writes require a real funded OpenAI Ads account. Start with small paused objects, review the returned ids and budgets, then activate only after explicit approval.

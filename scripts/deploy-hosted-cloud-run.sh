#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-trakkr-ai}"
REGION="${REGION:-us-east1}"
SERVICE="${SERVICE:-openai-ads-mcp}"
IMAGE="${IMAGE:-gcr.io/${PROJECT_ID}/${SERVICE}:$(git rev-parse --short HEAD)}"
DOMAIN="${DOMAIN:-openai-ads-mcp.trakkr.ai}"
TELEMETRY_SALT_SECRET="${TELEMETRY_SALT_SECRET:-openai-ads-mcp-telemetry-salt}"

if [[ -z "${OPENAI_ADS_MCP_TELEMETRY_SALT:-}" ]]; then
  echo "OPENAI_ADS_MCP_TELEMETRY_SALT is required." >&2
  exit 1
fi

cd "$(dirname "$0")/../typescript"

if gcloud secrets describe "${TELEMETRY_SALT_SECRET}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  printf '%s' "${OPENAI_ADS_MCP_TELEMETRY_SALT}" | gcloud secrets versions add "${TELEMETRY_SALT_SECRET}" \
    --project "${PROJECT_ID}" \
    --data-file=- >/dev/null
else
  printf '%s' "${OPENAI_ADS_MCP_TELEMETRY_SALT}" | gcloud secrets create "${TELEMETRY_SALT_SECRET}" \
    --project "${PROJECT_ID}" \
    --replication-policy=automatic \
    --data-file=- >/dev/null
fi

gcloud builds submit \
  --project "${PROJECT_ID}" \
  --tag "${IMAGE}" \
  .

gcloud run deploy "${SERVICE}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --image "${IMAGE}" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --concurrency 1 \
  --memory 256Mi \
  --cpu 0.25 \
  --timeout 15s \
  --update-env-vars "OPENAI_ADS_MCP_HOSTED_PUBLIC=1,OPENAI_ADS_MCP_READONLY=1,OPENAI_ADS_MCP_GLOBAL_TOOL_CALLS_PER_DAY=${OPENAI_ADS_MCP_GLOBAL_TOOL_CALLS_PER_DAY:-1000}" \
  --update-secrets "OPENAI_ADS_MCP_TELEMETRY_SALT=${TELEMETRY_SALT_SECRET}:latest"

echo "Deployed ${SERVICE}. Configure ${DOMAIN} through Cloudflare, then verify:"
echo "curl -fsS https://${DOMAIN}/health"
echo "curl -fsS https://${DOMAIN}/.well-known/mcp/server-card.json"

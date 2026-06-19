import { readFile } from "node:fs/promises";

const specUrl = "https://developers.openai.com/ads/openapi.json";
const localPath = new URL("../../openapi.json", import.meta.url);

function stable(value) {
  if (Array.isArray(value)) {
    return value.map(stable);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, stable(item)]),
    );
  }
  return value;
}

const response = await fetch(specUrl, { headers: { Accept: "application/json" } });
if (!response.ok) {
  throw new Error(`Could not download ${specUrl}: HTTP ${response.status}`);
}

const live = stable(await response.json());
const local = stable(JSON.parse(await readFile(localPath, "utf8")));

const liveText = JSON.stringify(live, null, 2);
const localText = JSON.stringify(local, null, 2);

if (liveText !== localText) {
  console.error("Vendored OpenAPI spec drift detected.");
  console.error("Refresh services/openai-ads-mcp/openapi.json from https://developers.openai.com/ads/openapi.json, then review tool validations.");
  process.exit(1);
}

console.log("Vendored OpenAPI spec matches the live OpenAI Ads spec.");

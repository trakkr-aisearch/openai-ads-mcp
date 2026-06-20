#!/usr/bin/env node
import { pathToFileURL } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { INSTRUCTIONS, isReadonlyMode, registerAdsTool, type AdsToolDefinition } from "./core.js";
import { helperTools } from "./helpers.js";
import { startHttpServer } from "./http.js";
import { registerTrakkrVisibilityResource } from "./resource_trakkr.js";
import { adGroupTools } from "./tools/adgroups.js";
import { adTools } from "./tools/ads.js";
import { accountTools } from "./tools/account.js";
import { audienceTools } from "./tools/audiences.js";
import { campaignTools } from "./tools/campaigns.js";
import { conversionTools } from "./tools/conversions.js";
import { insightTools } from "./tools/insights.js";

export const allToolDefinitions: AdsToolDefinition[] = [
  ...accountTools,
  ...campaignTools,
  ...adGroupTools,
  ...adTools,
  ...insightTools,
  ...audienceTools,
  ...conversionTools,
  ...helperTools,
];

export function registeredToolDefinitions(): AdsToolDefinition[] {
  return allToolDefinitions.filter((tool) => !(tool.writes && isReadonlyMode()));
}

export function registeredToolMetadata(): Array<{ name: string; args: string[] }> {
  return registeredToolDefinitions().map((tool) => ({ name: tool.name, args: [...tool.argNames] }));
}

export function createOpenAIAdsMcpServer(): McpServer {
  const server = new McpServer(
    {
      name: "OpenAI Ads",
      version: "0.1.4",
    },
    {
      instructions: INSTRUCTIONS,
    },
  );
  registerTrakkrVisibilityResource(server);
  for (const tool of allToolDefinitions) {
    registerAdsTool(server, tool);
  }
  return server;
}

export async function main(): Promise<void> {
  if (transportMode() === "http") {
    await startHttpServer();
    return;
  }
  const server = createOpenAIAdsMcpServer();
  await server.connect(new StdioServerTransport());
}

function transportMode(): "stdio" | "http" {
  const flag = process.argv.slice(2).find((arg) => arg === "--http" || arg === "http" || arg.startsWith("--transport="));
  if (flag === "--http" || flag === "http" || flag === "--transport=http") {
    return "http";
  }
  if ((process.env.OPENAI_ADS_MCP_TRANSPORT ?? "").trim().toLowerCase() === "http") {
    return "http";
  }
  return "stdio";
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`openai-ads-mcp failed to start: ${message}`);
    process.exitCode = 1;
  });
}

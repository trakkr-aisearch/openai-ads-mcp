import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { AuthInfo } from "@modelcontextprotocol/sdk/server/auth/types.js";

type AuthedIncomingMessage = IncomingMessage & { auth?: AuthInfo };

export interface HttpServerHandle {
  close: () => Promise<void>;
  url: string;
}

export interface HttpServerOptions {
  host?: string;
  port?: number;
  mcpPath?: string;
  healthPath?: string;
}

export async function startHttpServer(options: HttpServerOptions = {}): Promise<HttpServerHandle> {
  const { createOpenAIAdsMcpServer } = await import("./index.js");
  forceReadonlyForHttpUnlessExplicitlyEnabled();

  const host = options.host ?? process.env.HOST ?? "0.0.0.0";
  const port = options.port ?? parsePort(process.env.PORT ?? process.env.OPENAI_ADS_MCP_HTTP_PORT);
  const mcpPath = normalisePath(options.mcpPath ?? process.env.OPENAI_ADS_MCP_HTTP_PATH ?? "/mcp");
  const healthPath = normalisePath(options.healthPath ?? process.env.OPENAI_ADS_MCP_HEALTH_PATH ?? "/healthz");

  const mcpServer = createOpenAIAdsMcpServer();
  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });
  await mcpServer.connect(transport);

  const httpServer = createServer(async (req: AuthedIncomingMessage, res) => {
    try {
      const path = requestPath(req);
      setCorsHeaders(res);

      if (req.method === "OPTIONS") {
        res.writeHead(204);
        res.end();
        return;
      }

      if (req.method === "GET" && path === healthPath) {
        writeJson(res, 200, {
          ok: true,
          name: "openai-ads-mcp",
          transport: "streamable-http",
          readonly: process.env.OPENAI_ADS_MCP_READONLY === "1",
        });
        return;
      }

      if (path !== mcpPath) {
        writeJson(res, 404, { error: "not_found" });
        return;
      }

      if (!["GET", "POST", "DELETE"].includes(req.method ?? "")) {
        writeJson(res, 405, { error: "method_not_allowed" });
        return;
      }

      const auth = requestAuth(req);
      if (!auth.ok) {
        writeJson(res, auth.status, { error: auth.code });
        return;
      }
      req.auth = auth.info;
      await transport.handleRequest(req, res);
    } catch (error) {
      if (!res.headersSent) {
        writeJson(res, 500, { error: "internal_error" });
      } else {
        res.end();
      }
      process.stderr.write(`openai-ads-mcp HTTP transport error: ${errorName(error)}\n`);
    }
  });

  await new Promise<void>((resolve, reject) => {
    httpServer.once("error", reject);
    httpServer.listen(port, host, () => {
      httpServer.off("error", reject);
      resolve();
    });
  });

  const address = httpServer.address() as AddressInfo;
  const displayHost = host === "0.0.0.0" ? "127.0.0.1" : host;
  const url = `http://${displayHost}:${address.port}${mcpPath}`;
  process.stderr.write(`openai-ads-mcp listening on ${url}\n`);

  return {
    url,
    close: async () => {
      await mcpServer.close();
      await new Promise<void>((resolve, reject) => {
        httpServer.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}

function forceReadonlyForHttpUnlessExplicitlyEnabled(): void {
  if (truthy(process.env.OPENAI_ADS_MCP_HTTP_ALLOW_WRITES)) {
    return;
  }
  process.env.OPENAI_ADS_MCP_READONLY = "1";
}

function requestAuth(req: IncomingMessage):
  | { ok: true; info: AuthInfo }
  | { ok: false; status: number; code: string } {
  const requiredToken = (process.env.OPENAI_ADS_MCP_HTTP_TOKEN ?? "").trim();
  if (requiredToken && bearerToken(req.headers.authorization) !== requiredToken) {
    return { ok: false, status: 401, code: "unauthorized" };
  }

  const openaiAdsApiKey = singleHeader(req, "x-openai-ads-api-key");
  const openaiAdsApiBaseUrl = singleHeader(req, "x-openai-ads-api-base-url");
  if ((openaiAdsApiKey && openaiAdsApiKey.length > 400) || (openaiAdsApiBaseUrl && openaiAdsApiBaseUrl.length > 300)) {
    return { ok: false, status: 400, code: "invalid_openai_ads_credentials" };
  }

  return {
    ok: true,
    info: {
      token: requiredToken ? "mcp-http-token" : "anonymous",
      clientId: "openai-ads-mcp-http",
      scopes: truthy(process.env.OPENAI_ADS_MCP_HTTP_ALLOW_WRITES) ? ["ads:read", "ads:write"] : ["ads:read"],
      extra: {
        ...(openaiAdsApiKey ? { openaiAdsApiKey } : {}),
        ...(openaiAdsApiBaseUrl ? { openaiAdsApiBaseUrl } : {}),
      },
    },
  };
}

function bearerToken(value: string | undefined): string {
  const [scheme, token] = (value ?? "").split(/\s+/, 2);
  if (scheme?.toLowerCase() !== "bearer" || !token) {
    return "";
  }
  return token.trim();
}

function singleHeader(req: IncomingMessage, name: string): string {
  const value = req.headers[name];
  if (Array.isArray(value)) {
    return (value[0] ?? "").trim();
  }
  return (value ?? "").trim();
}

function requestPath(req: IncomingMessage): string {
  return new URL(req.url ?? "/", "http://localhost").pathname;
}

function normalisePath(path: string): string {
  const trimmed = path.trim();
  if (!trimmed || trimmed === "/") {
    return "/";
  }
  return `/${trimmed.replace(/^\/+|\/+$/g, "")}`;
}

function parsePort(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "", 10);
  if (Number.isInteger(parsed) && parsed >= 0 && parsed <= 65_535) {
    return parsed;
  }
  return 8080;
}

function setCorsHeaders(res: ServerResponse): void {
  const origin = process.env.OPENAI_ADS_MCP_HTTP_CORS_ORIGIN?.trim() || "*";
  res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "Authorization,Content-Type,Mcp-Protocol-Version,Mcp-Session-Id,X-OpenAI-Ads-API-Key,X-OpenAI-Ads-API-Base-Url",
  );
  res.setHeader("Access-Control-Expose-Headers", "Mcp-Session-Id");
}

function writeJson(res: ServerResponse, status: number, value: Record<string, unknown>): void {
  res.writeHead(status, {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
  });
  res.end(JSON.stringify(value));
}

function truthy(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value ?? "").trim().toLowerCase());
}

function errorName(error: unknown): string {
  return error instanceof Error ? error.name : "Error";
}

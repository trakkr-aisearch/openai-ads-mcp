const ORIGIN = "https://openai-ads-mcp-wnurzhwgia-ue.a.run.app";
const MAX_BODY_BYTES = 256 * 1024;
const PUBLIC_PATHS = new Set([
  "/mcp",
  "/health",
  "/healthz",
  "/ready",
  "/.well-known/mcp/server-card.json",
]);

export default {
  async fetch(request) {
    const incomingUrl = new URL(request.url);

    if (!PUBLIC_PATHS.has(incomingUrl.pathname)) {
      return json({ error: "not_found" }, 404);
    }

    if (!["GET", "HEAD", "POST", "DELETE", "OPTIONS"].includes(request.method)) {
      return json({ error: "method_not_allowed" }, 405, { Allow: "GET, HEAD, POST, DELETE, OPTIONS" });
    }

    const contentLength = Number(request.headers.get("content-length") || "0");
    if (contentLength > MAX_BODY_BYTES) {
      return json({ error: "request_too_large", max_bytes: MAX_BODY_BYTES }, 413);
    }

    const originUrl = new URL(incomingUrl.pathname + incomingUrl.search, ORIGIN);
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.set("x-forwarded-host", incomingUrl.host);
    headers.set("x-trakkr-edge", "cloudflare-worker");

    const response = await fetch(originUrl, {
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      headers,
      method: request.method,
      redirect: "manual",
    });

    const responseHeaders = new Headers(response.headers);
    if (incomingUrl.pathname === "/mcp") {
      responseHeaders.set("cache-control", "no-store");
    }

    return new Response(response.body, {
      headers: responseHeaders,
      status: response.status,
      statusText: response.statusText,
    });
  },
};

function json(body, status, headers = {}) {
  return new Response(JSON.stringify(body), {
    headers: {
      "content-type": "application/json",
      ...headers,
    },
    status,
  });
}

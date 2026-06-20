import { readFile } from "node:fs/promises";
import { basename } from "node:path";

export const API_BASE_URL = "https://api.ads.openai.com/v1";
export const CONVERSIONS_BASE_URL = "https://bzr.openai.com/v1";

const USER_AGENT = "openai-ads-mcp/0.1.4";

const FRIENDLY_ERRORS: Record<number, string> = {
  401: "Invalid or expired OPENAI_ADS_API_KEY.",
  403: "Access denied. Check whether this Ads account is eligible and has permission for this endpoint.",
  404: "Resource not found. Check the id and try again.",
  429: "Rate limited by the OpenAI Ads API. Wait a moment and retry.",
};

export class OpenAIAdsAPIError extends Error {
  readonly statusCode: number;
  readonly detail: string;

  constructor(statusCode: number, detail: string) {
    super(detail);
    this.name = "OpenAIAdsAPIError";
    this.statusCode = statusCode;
    this.detail = detail;
  }
}

export type JsonRecord = Record<string, unknown>;

export class OpenAIAdsClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;

  constructor(apiKey: string, baseUrl = API_BASE_URL) {
    if (!apiKey.trim()) {
      throw new Error("OPENAI_ADS_API_KEY is required.");
    }
    this.apiKey = apiKey;
    this.baseUrl = validateBaseUrl(baseUrl, "OPENAI_ADS_API_BASE_URL");
  }

  static fromEnv(): OpenAIAdsClient {
    return new OpenAIAdsClient(
      process.env.OPENAI_ADS_API_KEY ?? "",
      process.env.OPENAI_ADS_API_BASE_URL ?? API_BASE_URL,
    );
  }

  async get(path: string, params?: JsonRecord): Promise<JsonRecord> {
    return this.request(this.baseUrl, "GET", path, { params });
  }

  async post(path: string, body?: JsonRecord): Promise<JsonRecord> {
    return this.request(this.baseUrl, "POST", path, { json: body });
  }

  async uploadFile(path: string, filePath: string): Promise<JsonRecord> {
    const bytes = await readFile(filePath);
    const form = new FormData();
    form.append("file", new Blob([bytes]), basename(filePath));
    return this.request(this.baseUrl, "POST", path, { body: form });
  }

  async postConversions(pixelId: string, events: JsonRecord[]): Promise<JsonRecord> {
    return this.request(CONVERSIONS_BASE_URL, "POST", "/events", {
      params: { pid: pixelId },
      json: { events },
      redactDetail: true,
    });
  }

  private async request(
    baseUrl: string,
    method: string,
    path: string,
    options: {
      params?: JsonRecord;
      json?: JsonRecord;
      body?: BodyInit;
      redactDetail?: boolean;
    } = {},
  ): Promise<JsonRecord> {
    const url = buildUrl(baseUrl, path, options.params);
    const headers = new Headers({
      Accept: "application/json",
      Authorization: `Bearer ${this.apiKey}`,
      "User-Agent": USER_AGENT,
    });
    let body = options.body;
    if (options.json !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.json);
    }
    try {
      const response = await fetch(url, { method, headers, body, redirect: "manual" });
      if (!response.ok) {
        throw await toApiError(response, options.redactDetail === true);
      }
      const text = await response.text();
      if (!text) {
        return {};
      }
      return JSON.parse(text) as JsonRecord;
    } catch (error) {
      if (error instanceof OpenAIAdsAPIError) {
        throw error;
      }
      throw new OpenAIAdsAPIError(
        0,
        `Network error contacting OpenAI Ads API: ${error instanceof Error ? error.name : "Error"}`,
      );
    }
  }
}

async function toApiError(response: Response, redactDetail: boolean): Promise<OpenAIAdsAPIError> {
  const friendly = FRIENDLY_ERRORS[response.status];
  if (friendly) {
    return new OpenAIAdsAPIError(response.status, friendly);
  }
  if (response.status >= 500) {
    const requestId = response.headers.get("x-request-id");
    let message = "OpenAI Ads API is temporarily unavailable. Please try again shortly.";
    if (requestId) {
      message = `${message} Request ID: ${requestId}`;
    }
    return new OpenAIAdsAPIError(response.status, message);
  }
  let detail = `HTTP ${response.status}`;
  if (!redactDetail) {
    try {
      const body = (await response.json()) as Record<string, unknown>;
      detail = String(body.detail ?? body.message ?? JSON.stringify(body));
    } catch {
      detail = (await response.text()) || detail;
    }
  }
  return new OpenAIAdsAPIError(response.status, `API error (${response.status}): ${detail}`);
}

function buildUrl(baseUrl: string, path: string, params?: JsonRecord): string {
  const url = new URL(path.replace(/^\/+/, ""), `${baseUrl}/`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined && item !== null) {
          url.searchParams.append(key, String(item));
        }
      }
    } else {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

function validateBaseUrl(baseUrl: string, envName: string): string {
  const parsed = new URL(baseUrl);
  if (parsed.protocol !== "https:") {
    throw new Error(`${envName} must use https.`);
  }
  if (!parsed.hostname) {
    throw new Error(`${envName} must include a hostname.`);
  }
  if (parsed.username || parsed.password) {
    throw new Error(`${envName} must not include credentials.`);
  }
  if (parsed.search || parsed.hash) {
    throw new Error(`${envName} must not include query or fragment.`);
  }
  return baseUrl.replace(/\/+$/, "");
}

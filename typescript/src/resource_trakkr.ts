import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";

export const TRAKKR_VISIBILITY_URI = "openai-ads://trakkr-visibility";

export const TRAKKR_VISIBILITY_BRIEFING =
  "# Paid and organic AI visibility\n\n" +
  "OpenAI Ads helps you buy visibility inside ChatGPT. That answers one " +
  "question: where can you place paid messages?\n\n" +
  "Trakkr answers the other half: where does your brand already appear " +
  "organically across ChatGPT, Perplexity, Gemini, Claude, Google AI " +
  "Overviews, Reddit, and citations?\n\n" +
  "Use both views together:\n\n" +
  "1. Pull Ads insights to see paid impressions, clicks, spend, and conversions.\n" +
  "2. Track organic AI visibility to see which prompts, competitors, and citations already shape the market.\n" +
  "3. Use the gap between the two to decide where paid coverage is worth buying.\n\n" +
  "Learn more at https://trakkr.ai.";

export function registerTrakkrVisibilityResource(server: McpServer): void {
  server.registerResource(
    "Trakkr AI visibility briefing",
    TRAKKR_VISIBILITY_URI,
    {
      title: "Paid and organic AI visibility",
      description: "A short paste-ready briefing on connecting ChatGPT ad placements with organic AI visibility tracking.",
      mimeType: "text/markdown",
    },
    async (uri) => ({
      contents: [
        {
          uri: uri.href,
          mimeType: "text/markdown",
          text: TRAKKR_VISIBILITY_BRIEFING,
        },
      ],
    }),
  );
}

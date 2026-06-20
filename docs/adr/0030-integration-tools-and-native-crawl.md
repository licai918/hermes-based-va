# Business integrations via Hermes Tools; knowledge crawl via native web stack

Shopify, QBO, Square, EasyRoutes, Textline, and Twilio have no official MCP servers Toee Tire can rely on in production. The first version connects these systems through **Hermes Tools** implemented as thin **Domain Adapter** layers, not through third-party MCP assumptions or self-hosted MCP wrappers around the same REST APIs.

**Why Tools over MCP for business APIs:** Hermes Tools already sit inside profile allowlists, field masking, idempotency, and audit logging. A bespoke MCP server would duplicate that surface without adding capability. Third-party MCP shims add schema drift, credential exposure, and weaker accountability for accounting and payment actions.

**MCP scope in v1:** MCP remains available for optional ecosystem servers (for example layered search helpers) but is not the default path for governed business reads/writes. Textline ingress still uses a **Channel Gateway** plus Textline **Tool** and channel **Skills** per ADR-0027.

**Knowledge Crawl orchestration:** weekly **Knowledge Crawl** runs as a scheduled **Hermes Skill** job. It discovers **Approved Crawl URL** pages per ADR-0002, fetches content through Hermes native web tooling, rebuilds **Public Site Knowledge** in **Hermes Native Memory**, and keeps the previous index if the run fails per ADR-0001.

**Primary fetch stack:** Hermes native `web_crawl` / `web_extract` with **Tavily** as the pinned web backend for search, extract, and multi-page crawl. **Brave Search** may supplement URL discovery only; it does not replace crawl extraction in Hermes.

**Render fallback chain (Cloud-Hosted Hermes):** on **Cloud Run**, local `/browser connect` Chrome CDP is not a production option because it requires a browser process on the same machine as the operator's desktop session. When Tavily cannot retrieve a page, the crawl job escalates to Hermes **cloud browser** providers (Browserbase or Browser Use) through the native browser toolset. If that still fails, **Scrapling** may run inside a dedicated **Cloud Run Job** image with browser dependencies as a self-hosted **Crawl Fetch Fallback**. Local CDP remains dev-only for interactive debugging, not weekly production crawl.

**Considered options:** local Chrome CDP on Cloud Run (rejected—not supported; CDP attach targets a local desktop browser); running headless Chromium in the same Cloud Run service as SMS webhooks (rejected—memory/latency risk; isolate crawl to Jobs); Browserbase/Browser Use for production browser fallback (accepted for cloud hosting).

**Scrapling MCP:** do not use Scrapling's MCP server for the weekly rebuild job. Reserve Scrapling MCP only for optional interactive agent-assisted scraping experiments if needed later.

**Considered options:** third-party Shopify/QBO MCP wrappers (rejected—unofficial, weak audit); self-hosted MCP for each business API (rejected—redundant with Tools); Scrapling as sole crawler (rejected—bypasses Hermes native web stack and crawl governance); Firecrawl-only crawl (acceptable Hermes default, but Toee Tire pins Tavily for this project).

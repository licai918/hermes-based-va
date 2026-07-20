# Knowledge crawl URL scope for toeetire.com

> **Superseded (2026-07-20).** No crawl exists or is planned. The weekly sitemap crawl this ADR
> scopes was never implemented, and the 0.0.3 spike ingests storefront content directly through
> the Shopify connector instead — so URL-discovery scope and the 100-URL cap no longer apply.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md) (L5).

Weekly **Knowledge Crawl** discovers public pages from `toeetire.com` via sitemap and indexes only approved public content into **Public Site Knowledge**. The first version caps discovery at 100 URLs.

**Included:** sitemap-listed public pages such as `/pages/*`, policy pages, blogs/news, and `/products/*` for stable product education (not live price or inventory).

**Excluded:** `/cart`, `/checkout`, `/account`, login pages, search-result URLs, and any URL with query parameters.

**Language:** English public pages only in the first version; French pages are out of scope until explicitly added.

**Considered options:** crawling the entire site without caps (rejected—noise and cost); including French from day one (rejected—no confirmed bilingual support need for MVP).

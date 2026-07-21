# Shopify-primary knowledge sync with Tavily gap crawl before go-live

> **Mechanism superseded, source vindicated (2026-07-20).** **Still holds:** Shopify as the
> primary source of storefront knowledge — the 0.0.3 spike pulled its entire corpus (pages,
> blog articles, shop policies) from the Shopify connector, confirming this ADR's source
> choice — and "live conversation facts stay on tool paths, not RAG". **Superseded:** the
> weekly scheduled Hermes Skill, the **Tavily Gap Crawl**, and writing into Hermes Native
> Memory; retrieval is now an in-house hybrid lexical + embedding index in a separate database.
> Formal superseding decision → [ADR-0149](0149-hybrid-lexical-embedding-knowledge-retriever.md).
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md) (L5).

Before **Text-First Launch**, **Public Site Knowledge** rebuild uses a dual-track ingestion model. **Shopify Knowledge Sync** is the primary source; **Tavily Gap Crawl** supplements URLs and content not covered by the Shopify Admin API.

**Shopify Knowledge Sync** runs weekly as a scheduled Hermes Skill. It reads Shopify Admin API content—products (titles, descriptions, education copy, image metadata), pages, blogs/articles, and shop policies—and writes normalized records into **Hermes Native Memory** for retrieval. This is the authoritative source for storefront content that already lives in Shopify.

**Tavily Gap Crawl** runs in the same weekly rebuild window after Shopify sync completes. It fetches only **Approved Crawl URL** pages from the sitemap that Shopify sync did not index, plus any approved public URLs still missing from the combined index. Tavily remains pinned as the web backend per ADR-0030. **Brave Search** may assist discovery only. Browser and Scrapling fallbacks apply only to gap URLs per ADR-0030.

**Live conversation facts** stay on **Business Integration Tool** paths, not RAG. Product price, inventory, order status, and **Product Media Reply** image URLs must come from live Shopify Tool reads at request time. Weekly sync may index product education text, but must not substitute cached sync data for live commerce facts per ADR-0001 and ADR-0020.

**Product Media Reply:** when a customer requests a product image over Textline SMS, Hermes resolves the product through the Shopify Tool and sends the image or an approved product page link through the Textline Tool in the **current SMS Session**. **Unmatched Caller** and **Verified Customer** may both receive public-catalog media. A **Verified Customer** may also receive live price and inventory in the same reply when requested.

**Web tools retained:** Tavily and other Hermes web tools remain available for ad-hoc retrieval when neither Shopify sync nor gap crawl indexed the needed content, and for external references outside toeetire.com.

**Failure behavior:** if Shopify sync fails, the rebuild keeps the previous Shopify-backed index and still attempts Tavily gap crawl. If the entire rebuild fails, Hermes keeps serving the last successful index per ADR-0001.

**Considered options:** Tavily-only rebuild through go-live (rejected—user chose dual-track before launch); Shopify-only with no Tavily (rejected—API gaps and external references still need web fallback); using RAG-cached product images for SMS (rejected—live media must come from Shopify Tool).

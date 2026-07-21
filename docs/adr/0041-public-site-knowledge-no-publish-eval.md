# Knowledge Publish Eval Gate applies only to operational policy

> **Knowledge pipeline superseded (2026-07-20).** Still holds: the governance
> asymmetry — **Operational Policy Knowledge** needs the ADR-0040 eval gate, the shared
> non-PII corpus does not, and Shopify plus the public website stay the human-maintained
> source. Superseded: weekly **Shopify Knowledge Sync**, **Tavily Gap Crawl**, the weekly
> rebuild window, and keep-previous-index-on-failure; the corpus now loads from the
> Shopify connector.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

The **Knowledge Publish Eval Gate** governs **Operational Policy Knowledge** only. It does not gate weekly **Shopify Knowledge Sync** or **Tavily Gap Crawl** updates to **Public Site Knowledge**.

When **Shopify Knowledge Sync** or **Tavily Gap Crawl** completes successfully, Hermes rebuilds the external retrieval index for **Public Site Knowledge** without a separate publish-eval step. The public website and Shopify Admin API remain the human-maintained source of truth for that layer.

If a weekly rebuild fails, Hermes keeps serving the previous **Public Site Knowledge** index per ADR-0001 and ADR-0031.

**Operational Policy Knowledge** still requires eval pass before promotion to **Published Operational Policy** per ADR-0040.

**Considered options:** require eval after every weekly Shopify sync (rejected for v1—adds latency without matching the governance model of internally authored policy); auto-publish operational policy without eval (rejected—already blocked by ADR-0040); diff-threshold eval for public-site changes (deferred to a later version if drift risk appears).

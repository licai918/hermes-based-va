# Hybrid knowledge with weekly local RAG rebuild

> **Retrieval mechanism superseded (2026-07-20).** The weekly **Knowledge Crawl** rebuild was
> never implemented, and the "no separate vector database" constraint no longer holds: the 0.0.3
> spike selected an in-house **hybrid lexical + dense-embedding** retriever over a separate
> index. The storage substrate goes with it: knowledge is not stored through **Hermes Native
> Memory** but in a separate no-PII database loaded from the Shopify connector.
> **Still holds:** the two-layer split (Public Site Knowledge vs governed Operational
> Policy Knowledge), "account-specific facts come from live tools, not RAG", and keeping public
> copy on the website rather than a second hand-authored corpus.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md) (L5).

Toee Tire will use a two-layer knowledge model for Hermes: **Public Site Knowledge** crawled from `toeetire.com`, plus a small set of internally governed **Operational Policy Knowledge** for verification, payment-link, and after-hours rules that the public site does not encode. Public FAQ and policy copy are maintained only on the website; Hermes does not maintain a second public FAQ corpus.

**Knowledge Crawl** runs automatically once per week. Each run fetches approved public pages, rebuilds the retrieval index, and stores searchable knowledge through **Hermes Native Memory** and/or Hermes-native knowledge Skills/Tools/MCP paths. The first version does not use Google Vertex RAG or a separate vector database such as pgvector or Chroma. Account-specific facts (orders, AR, delivery, payments) still come from live tools, not RAG.

Supervisors may trigger a manual rebuild after major policy changes. If a weekly crawl fails, Hermes keeps serving the previous index until the next successful rebuild.

**Considered options:** daily crawl (rejected for MVP—weekly is enough for policy/FAQ cadence); Google Vertex RAG only (rejected—adds GCP coupling and changes without reducing Hermes core edits); real-time website fetch at answer time (rejected—latency and inconsistency).

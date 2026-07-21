# Hermes-native development over Gemini VA porting

> **Memory and crawl clauses superseded (ADR-0140/0142; 0.0.3 knowledge decision).**
> Still holds: build on **Hermes Core** native surfaces instead of porting Gemini VA
> modules, thin adapters, no reimplementing Hermes orchestration, profile gating, or
> tool routing, and Gemini VA as read-only reference. Superseded: the **Memory:** clause
> requiring all conversational, customer, case, consent, and operational memory to live in
> **Hermes Native Memory** with no "bespoke application database" — the **Toee Business
> Datastore** (Postgres) is the system of record and Hermes native memory is
> conversation-only; and the website knowledge-crawl mentions under **Integrations:** and
> **Implication for prior decisions:**, since no crawl exists or is planned. ADR-0110's
> rejected-options line cites this ADR to reject a PostgreSQL preference table; that
> rejection no longer applies.
> Current direction → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

Toee Tire **Hermes VA** should be built on **Hermes Core** native architecture as much as possible. The prior Gemini VA codebase is a domain and policy reference, not a module porting source.

**Memory:** all conversational, customer, case, consent, and operational memory must live in **Hermes Native Memory**, not a parallel Gemini-style store or bespoke application database invented for this project.

**Integrations:** Shopify, QBO, Square, EasyRoutes, Textline, Twilio, and website knowledge crawl should connect through **Hermes Skills**, **Hermes Tools**, and **Hermes MCP** using the native extension surfaces Hermes already supports. Adapters should be thin; orchestration, permissions, and memory stay in Hermes.

**Scope rule:** do not reimplement Hermes orchestration, profile gating, memory, or tool routing. Do not copy Gemini VA agentos, memory_store, or channel glue wholesale. Reuse from Gemini VA only as read-only reference for business rules, eval scenarios, and policy wording when helpful.

**Implication for prior decisions:** weekly knowledge crawl, identity graph behavior, follow-up cases, and audit requirements still hold, but their storage and execution paths must map onto Hermes-native Skills/Tools/MCP and memory—not Gemini VA primitives.

**Considered options:** fork Gemini VA python-backend modules into Hermes (rejected—duplicates non-native memory and orchestration); greenfield custom core (rejected—conflicts with Hermes-native goal).

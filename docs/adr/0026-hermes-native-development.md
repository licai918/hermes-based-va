# Hermes-native development over Gemini VA porting

Toee Tire **Hermes VA** should be built on **Hermes Core** native architecture as much as possible. The prior Gemini VA codebase is a domain and policy reference, not a module porting source.

**Memory:** all conversational, customer, case, consent, and operational memory must live in **Hermes Native Memory**, not a parallel Gemini-style store or bespoke application database invented for this project.

**Integrations:** Shopify, QBO, Square, EasyRoutes, Textline, Twilio, and website knowledge crawl should connect through **Hermes Skills**, **Hermes Tools**, and **Hermes MCP** using the native extension surfaces Hermes already supports. Adapters should be thin; orchestration, permissions, and memory stay in Hermes.

**Scope rule:** do not reimplement Hermes orchestration, profile gating, memory, or tool routing. Do not copy Gemini VA agentos, memory_store, or channel glue wholesale. Reuse from Gemini VA only as read-only reference for business rules, eval scenarios, and policy wording when helpful.

**Implication for prior decisions:** weekly knowledge crawl, identity graph behavior, follow-up cases, and audit requirements still hold, but their storage and execution paths must map onto Hermes-native Skills/Tools/MCP and memory—not Gemini VA primitives.

**Considered options:** fork Gemini VA python-backend modules into Hermes (rejected—duplicates non-native memory and orchestration); greenfield custom core (rejected—conflicts with Hermes-native goal).

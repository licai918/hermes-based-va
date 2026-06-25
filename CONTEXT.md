# Hermes VA Context

This context defines the shared language for the Hermes virtual assistant used by Toee Tire customer service.

## Language

**Hermes VA**:
The virtual assistant system that handles customer-service conversations through approved profiles, knowledge, and business tools.
_Avoid_: Bot, generic AI, phone system

**Hermes Core**:
The shared text-based orchestration layer behind all Hermes profiles.
_Avoid_: Voice model, phone agent, self-built Gemini application core

**Cloud-Hosted Hermes**:
The production deployment model that runs **Hermes Core** on Google Cloud Run and activates additional Google Cloud services only when **Hermes Core** capabilities require them.
_Avoid_: Fixed infrastructure bundle, infrastructure-first provisioning

**Hermes Native Memory**:
The built-in Hermes memory system where Toee Tire stores conversation, customer, case, consent, and operational context for all profiles and channels. Toee Tire partitions it into the **Identity Graph**, conversation, operational, and **Customer Memory** layers.
_Avoid_: Gemini memory store, parallel custom memory database, channel-specific memory silos

**Customer Memory**:
The structured preference layer in **Hermes Native Memory** for durable service preferences. v1 slots are `contact_time_preference`, `channel_preference`, `delivery_habit_note`, and `communication_style_note`, bound through the **Identity Graph** to `shopifyCustomerId` when verified or provisionally to `channelIdentityId` when not. Provisional records merge onto the verified customer node when ingress identity first resolves to a **Verified Customer**. Runtime reads inject a compact preference block per turn; writes use governed customer-memory tools only.
_Avoid_: Live order or AR facts, operational policy text, SMS opt-out consent, model-guessed account data, open-ended preference keys, autonomous inferred writes, overwriting verified slots on merge, model-writable preference injection

**Hermes Integration Surface**:
The native Hermes extension model used to connect external systems through Skills, Tools, and MCP without replacing Hermes orchestration.
_Avoid_: Custom integration framework, copied Gemini VA tool glue, direct LLM-side hacks

**Domain Adapter**:
A thin Toee Tire-specific Skill, Tool, or MCP wrapper that implements business rules while delegating memory, permissions, and orchestration to **Hermes Core**.
_Avoid_: Full custom agent core, Gemini VA module port

**Hermes Runtime Shim**:
The Python Hermes-integration layer — the `toee_hermes` plugin plus the gateway embedding — that boots and embeds the upstream Python `hermes-agent`, selects a **Hermes Profile**, and registers **Domain Adapter Tools** without reimplementing orchestration, **Hermes Native Memory**, or **Tool Gate** logic. It is the only repo layer that imports Hermes (`hermes_agent` / `run_agent`); `apps/workbench` never imports Hermes and reaches per-profile Hermes over the API Server (HTTP) per ADR-0139.
_Avoid_: TypeScript in-process Hermes SDK, npm `packages/hermes-runtime` wrapper, custom agent core, forked Hermes source, direct Hermes imports from UI, BFF, or domain adapter code

**Hermes Built-in Tool**:
A tool shipped with **Hermes Core**, such as `web_search` or `memory`, registered through the same native tool surface as **Domain Adapter Tools**.
_Avoid_: Shopify/QBO business tool, Toee Tire policy tool

**Profile Tool Allowlist**:
The set of **Hermes Built-in Tools** and **Domain Adapter Tools** a **Hermes Profile** registers for agent use. Unlisted tools are not callable by that profile.
_Avoid_: Skill-only access control, prompt-only permission hope

**Hermes Profile**:
A governed operating mode of Hermes with its own audience, permissions, knowledge scope, and response policy.
_Avoid_: Separate Hermes, separate bot

**External Customer Service Profile**:
The Hermes Profile used for customer-facing phone, SMS, email, and web chat conversations.
_Avoid_: Internal assistant, supervisor agent, Textline as a separate profile

**Channel Gateway**:
The thin ingress layer that receives channel webhooks such as Textline or Twilio, verifies authenticity, and routes normalized events into the correct **Hermes Profile**.
_Avoid_: Channel-specific agent brain, business logic in webhook handler

**InboundChannelEvent**:
The canonical normalized payload for an accepted inbound customer message after **Channel Gateway** provider-specific mapping. Textline SMS uses channel `textline_sms` and includes ids, sender phone, body, optional media, and receipt time for idempotent ingress.
_Avoid_: Raw provider webhook JSON in agent prompts, processing delivery receipts as customer turns

**Webhook Acknowledgment**:
The point at which the **Channel Gateway** returns success to a provider after durable inbound preprocessing. For Textline SMS, Hermes returns `200` after verification, normalization, ingress matching, and inbound persistence, then runs the external agent asynchronously.
_Avoid_: Waiting for full agent completion before provider ack, acknowledging before persistence, using provider retries to replay completed inbound events

**AgentTurnContext**:
The persisted inbound-turn record that binds an accepted Textline message to `eventId`, `conversationId`, `smsSessionId`, **Customer Thread**, sender phone, and **Session Identity Snapshot** for async agent execution and governed outbound replies.
_Avoid_: Queue payload as source of truth, reply targeting from model-supplied alternate phone numbers, session re-resolution without ingress snapshot

**Customer Thread**:
The long-lived customer conversation record in **Hermes Native Memory** for a channel identity such as a Textline phone number, spanning multiple **SMS Session** windows and many **MessageTurn** records.
_Avoid_: One-message memory, channel-only log outside Hermes, case-owned thread container

**MessageTurn**:
One persisted inbound, outbound, or Hermes message record inside an **SMS Session** on a **Customer Thread**.
_Avoid_: Case-embedded message list, ephemeral agent-only turn history

**Copilot Gateway**:
The internal chat surface in the **Copilot Workbench** where employees converse with **Hermes Core** through the **Internal Copilot Profile**. On `/copilot` it stays idle until a **Human Intervention Case** is selected; audit routes hide it entirely.
_Avoid_: Customer chat portal, separate internal agent, drafting without selected case, gateway on read-only audit routes

**Operations Dashboard**:
The case and operations view in the **Copilot Workbench** showing **Human Intervention Case** queue items, urgency, conversation history, and resolution status from **Hermes Native Memory**. On the default `/copilot` route it uses a dual-zone left layout: **Case Queue** plus read-only **Case Thread Context** for the selected case.
_Avoid_: Separate ticketing system, dashboard without Hermes context, default queue of auto-handled threads, peer audit tabs on the rep default page

**Case Thread Context**:
The read-only full channel thread history shown in the **Operations Dashboard** when an employee opens a **Human Intervention Case**, including prior **Auto-Handled Interaction** turns on that channel, with the active case highlighted. A sticky header bar above the timeline shows case metadata and `toee_case_manage` actions such as claim, assign, contact-reason update, and resolve.
_Avoid_: Case-only message fragment, editable conversation history, cross-channel merged timeline in v1, case actions only in queue rows or Copilot header

**Auto-Handled Audit View**:
A read-only **Copilot Workbench** view for **Workbench Supervisor** and **Workbench Admin** users to review **Auto-Handled Interaction** records for quality sampling and compliance. The list shows shared audit columns plus tool summary and tool-failure markers, sorted by most recent activity first.
_Avoid_: Rep default work queue, draft or send actions, hidden untracked conversations, assignee or claim controls

**Sales Outreach Audit View**:
A read-only **Copilot Workbench** view for **Workbench Supervisor** and **Workbench Admin** users to sample low-priority **Follow-up Case** records with **Contact Reason** `sales_outreach`. The list shows shared audit columns plus case id and created time, sorted by most recent activity first.
_Avoid_: Rep default work queue, customer-service drafting queue, hidden untracked sales cases, assignee or claim controls

**Agent Workload View**:
A supervisor-facing **Case Queue** filter set on `/copilot` that lets **Workbench Supervisor** and **Workbench Admin** users scope **Human Intervention Case** rows by **Case Assignee**, including an all-team view and optional resolved-case review.
_Avoid_: Anonymous team inbox, untracked ownership, separate workload app, rep access to all-team queue by default

**Case Assignee**:
The **Workbench Account** currently responsible for handling a **Follow-up Case**.
_Avoid_: Shared case ownership, unlogged handoff

**Workbench Audit Log**:
The per-action accountability record in **Hermes Native Memory** for workbench events such as case view, assignment, draft generation, and resolution.
_Avoid_: Untracked employee actions, external-only audit spreadsheet

**Text-First Launch**:
The first-version go-live strategy that exposes the **External Customer Service Profile** on Textline SMS before adding the voice layer.
_Avoid_: Phone-first go-live, parallel multi-channel launch

**Voice Layer**:
The Twilio ConversationRelay and Net2phone transfer stack added after **Text-First Launch** validates Hermes text core, tools, and policy boundaries.
_Avoid_: Separate voice-only agent, phone brain fork

**Internal Copilot Profile**:
The Hermes Profile used by employees to review context, draft responses, and decide next actions through the **Copilot Gateway**.
_Avoid_: Customer-facing agent, separate deployed assistant

**Copilot Draft Action**:
A v1 **Internal Copilot Profile** capability that generates SMS, email, or internal notes for employee review without sending or writing to business systems.
_Avoid_: Autonomous customer send, accounting write, payment link creation

**Copilot Governed Write**:
A phased capability in which employees trigger approved write actions through **Copilot Gateway** only after explicit confirmation, role checks, and **Tool Gate** enforcement. Phase 1 is employee-confirmed Textline send from an editable **Copilot Draft Action** card and confirmation modal within a claimed **Human Intervention Case**.
_Avoid_: Autonomous AI write, unconfirmed one-click send, bypass of source-system controls, send outside an active human-intervention case

**Copilot Workbench**:
The internal workspace combining the **Copilot Gateway** and **Operations Dashboard** for case review, conversation context, and suggested next actions through the **Internal Copilot Profile**.
_Avoid_: Customer portal, passive ticket UI only, merged supervisor governance console

**Admin Governance Console**:
The internal workspace entry that uses the **Supervisor Admin Profile** for **KnowledgeOps**, eval review, and workbench administration. v1 uses three routes: `/admin/knowledge`, `/admin/eval`, and `/admin/accounts`.
_Avoid_: Customer case drafting, Textline send, live external customer-service reads, single-tabbed admin hub

**Customer Service Rep**:
An employee role authorized to use the **Copilot Workbench** to review cases, read summaries and transcripts, draft replies, and mark **Case Resolution**.
_Avoid_: Supervisor, company-wide staff access

**Workbench Supervisor**:
An employee role with **Customer Service Rep** access plus priority control, **Knowledge Gap Prompt** completion, and medium-severity **Launch Eval Gate** sign-off.
_Avoid_: Customer Service Rep only, unauthenticated admin

**Workbench Admin**:
An employee role that manages Hermes user access and system configuration; in a small team may also perform **Workbench Supervisor** duties.
_Avoid_: Customer-facing agent, default access for all employees

**Workbench Account**:
A self-managed username and password login provisioned by a **Workbench Admin** for authorized employees to access the **Copilot Workbench**.
_Avoid_: Google SSO, company-wide automatic access, customer login

**Workbench Password Policy**:
The minimum password and session rules for **Workbench Account** access, including length, complexity, login lockout, and inactivity timeout.
_Avoid_: Shared passwords, no lockout, permanent sessions

**Case Resolution**:
The process by which an employee reviews a **Follow-up Case**, takes action in source systems, and marks the case complete.
_Avoid_: Automatic closure, AI resolution

**Supervisor Admin Profile**:
The Hermes Profile used by authorized supervisors to manage knowledge, policies, quality review, and workbench administration without directly serving customers.
_Avoid_: Regular copilot, customer-facing send tools, live external-service reads for customer answers

**Opening Greeting**:
The first spoken message a caller hears when Hermes answers a phone conversation transferred from Net2phone.
_Avoid_: IVR menu, static script only, separate scripts per transfer trigger

**SMS Session Opener**:
The brief English identity introduction Hermes includes in the first reply of a new **SMS Session** before answering the customer's question.
_Avoid_: Repeated opener on every SMS, voice greeting script, long disclaimer block, email support signature

**Email Support Signature**:
The brief English AI-support identification line Hermes appends to every outbound email on the email channel using one fixed published signature text for all senders.
_Avoid_: SMS session opener, one-time thread-only introduction, improvised signature text, verified-customer company-name variants

**Personalized Opening Greeting**:
An **Opening Greeting** that changes based on the inbound phone number and the matched Shopify Customer context, but not based on Net2phone transfer trigger.
_Avoid_: Separate after-hours and no-answer scripts, fully static greeting, caller-specific freeform script

**Greeting Personalization Boundary**:
The limit on what customer-specific information Hermes may say in a **Personalized Opening Greeting**.
_Avoid_: Full account disclosure, opening balance readout

**KnowledgeOps**:
The internal governance process for drafting, reviewing, publishing, evaluating, and rolling back approved Hermes knowledge through `/admin/knowledge` using a slot-list and slot-editor master-detail layout.
_Avoid_: Customer training, automatic learning, eval sign-off on the knowledge editor page

**Pending Eval Knowledge**:
An operational policy or governed knowledge version that has been submitted for publish but is not yet customer-effective until the **Knowledge Publish Eval Gate** passes.
_Avoid_: Published customer policy, draft placeholder with no publish attempt, immediate external activation

**Published Operational Policy**:
The customer-effective version of **Operational Policy Knowledge** currently served to the **External Customer Service Profile** after passing the **Knowledge Publish Eval Gate**.
_Avoid_: Draft policy, pending eval version, website crawl content

**Knowledge Publish Eval Gate**:
The evaluation step required before new or rolled-back **Operational Policy Knowledge** becomes **Published Operational Policy** for external use.
_Avoid_: Optional QA, publish without validation, gating weekly **Public Site Knowledge** rebuilds

**Public Site Knowledge**:
Customer-facing information sourced from the Toee Tire public website and indexed for Hermes retrieval, primarily through **Shopify Knowledge Sync** and supplemented by **Tavily Gap Crawl**.
_Avoid_: Internal SOP, tool output, live website fetch at answer time

**Shopify Knowledge Sync**:
The scheduled weekly process that reads Shopify Admin API content such as products, pages, blogs, and shop policies into **Public Site Knowledge**.
_Avoid_: Live order lookup, cached product image send, replacement for Tavily on all URLs

**Tavily Gap Crawl**:
The supplemental weekly crawl that indexes only **Approved Crawl URL** pages not already covered by **Shopify Knowledge Sync**.
_Avoid_: Full-site primary crawl, customer-time browsing

**Product Media Reply**:
A Textline SMS reply that sends one public-catalog product image or approved product page link resolved through a live Shopify Tool read in the **current SMS Session**. A **Verified Customer** may receive live price and inventory in the same reply when requested.
_Avoid_: RAG-cached image URL, stale weekly sync media, payment link, account-scoped pricing or inventory for unmatched callers

**Prior Order Product Reference**:
A customer phrase such as "the one I ordered last time" that Hermes may resolve to a single Shopify order line item for a **Verified Customer** when recent order history uniquely identifies one product.
_Avoid_: Unmatched order inference, guessing across multiple recent orders, RAG-based product guess

**Operational Policy Knowledge**:
Hermes-specific rules that are not reliably represented on the public website, such as verification, payment-link, and after-hours boundaries.
_Avoid_: Marketing copy, website FAQ only

**Required Operational Policy Slot**:
One of the six mandatory **Operational Policy Knowledge** categories that Hermes must define before policy-bound customer service can rely on governed answers.
_Avoid_: Optional FAQ, website page, crawl-generated content

**Operational Policy Placeholder**:
A structured but unfilled **Required Operational Policy Slot** that exists in Hermes from onboarding onward until **KnowledgeOps** publishes approved content.
_Avoid_: Missing category, implicit default policy

**Knowledge Gap Prompt**:
A proactive question flow in which Hermes asks authorized **Supervisor Admin Profile** users to supply missing content for unfilled **Required Operational Policy Slots**.
_Avoid_: Customer interview, automatic policy generation, website crawl

**Knowledge Crawl**:
The scheduled process that fetches approved public website pages and refreshes the local retrieval index used by Hermes.
_Avoid_: Real-time browsing, customer conversation ingestion

**Business Integration Tool**:
A governed **Domain Adapter Tool** that reads or triggers approved actions in Shopify, QBO, Square, EasyRoutes, Textline, or Twilio under profile allowlists and audit rules.
_Avoid_: Third-party MCP wrapper, direct LLM-side API call, separate tool runtime outside Hermes

**Domain Adapter Tool Action**:
A named operation inside a **Domain Adapter Tool**, selected through a required `action` parameter with a fixed v1 enum and enforced by **Tool Gate** checks.
_Avoid_: Free-form tool parameters, separate Hermes tool registration per operation, skill-only enforcement

**Tool Gate**:
A programmatic check inside a **Business Integration Tool** or **Channel Gateway** that blocks or reshapes an action based on identity state, profile, and policy regardless of model behavior. Implemented in Toee Tire **Domain Adapter** code on the native Hermes Tools API, not as a separate Hermes core module.
_Avoid_: Skill-only policy, prompt-only enforcement, expecting a built-in Hermes policy engine

**Skill Guidance**:
Procedural instructions in Hermes Skills that tell the agent how to perform a task, but do not by themselves enforce customer-service policy boundaries.
_Avoid_: Treating Skills as compliance control, assuming the model always loads a Skill

**Crawl Fetch Fallback**:
A secondary fetch attempt used during **Knowledge Crawl** when the primary Hermes web retrieval path cannot retrieve an **Approved Crawl URL**. On **Cloud-Hosted Hermes**, this uses cloud browser providers or an isolated crawl job—not local desktop Chrome CDP.
_Avoid_: Replacing the primary crawl pipeline, customer-time live scraping, local `/browser connect` in production

**Approved Crawl URL**:
A public `toeetire.com` page that Hermes may fetch during **Knowledge Crawl**, such as pages, policies, blogs, and product education pages discovered from the site sitemap.
_Avoid_: Checkout page, account page, cart page, login page, dynamic search URL

**Verified Customer**:
A customer whose inbound phone number on voice or Textline SMS matches a phone number stored on a Shopify Customer record.
_Avoid_: Caller, phone number owner, manually verified customer

**Phone Match Verification**:
The first-version identity check that matches the inbound sender phone number against Shopify Customer **Registered Phone** records on Textline SMS and voice. For SMS, **Ingress Phone Match** runs synchronously in the **Channel Gateway** before **Hermes Core** processes the message, so verification is complete at message receipt without a customer-facing verification ceremony.
_Avoid_: Multi-factor verification, knowledge-based authentication, channel-specific SMS rules, pre-answer "verify your identity" prompts

**Ingress Phone Match**:
The synchronous phone-number lookup the **Channel Gateway** performs on every inbound Textline SMS before agent invocation, producing the current **Session Identity Snapshot**.
_Avoid_: Mid-conversation verification ritual, deferred identity lookup, customer-entered verification codes

**Session Identity Snapshot**:
The per-**SMS Session** identity outcome stored in the **Identity Graph**, including verified, unmatched, or ambiguous phone-match state and any matched Shopify customer identifiers.
_Avoid_: Permanent verified flag across sessions, agent-only memory without durable record, editable verification history

**Registered Phone**:
The phone number stored on a Shopify Customer record for a Toee Tire account. In normal operation this value is unique across Shopify Customers.
_Avoid_: Any caller phone, alternate contact number

**Ambiguous Phone Match**:
A situation where one inbound phone number matches more than one Shopify Customer **Registered Phone** record.
_Avoid_: Duplicate account, shared phone by default

**Ambiguous Email Match**:
A situation where one inbound sender address matches more than one Shopify Customer **Registered Email** record on the email channel.
_Avoid_: Duplicate account, shared inbox by default, auto-select first match

**Unmatched Caller**:
An inbound party whose phone does not match any Shopify Customer **Registered Phone** and whose stated intent indicates customer account, order, delivery, billing, or product purchase service.
_Avoid_: Non-customer contact, unverified customer, guest caller, supplier, government agency

**Non-Customer Contact**:
An inbound party on an external channel whose stated purpose is not Toee Tire customer account service, such as a government agency, supplier, temporary worker, **Sales Outreach**, or **Named Recipient Request**.
_Avoid_: Unmatched Caller, Verified Customer, internal employee

**Sales Outreach**:
A **Non-Customer Contact** attempting to sell services or products to Toee Tire rather than request customer account support. Hermes sends a brief decline and always creates a low-priority **Follow-up Case** for audit sampling.
_Avoid_: Supplier invoice follow-up, customer product inquiry, marketing message from Toee Tire, auto-handled dismissal without case

**Named Recipient Request**:
A **Non-Customer Contact** trying to reach a specific Toee Tire employee or role by name rather than request customer account support. Hermes collects the requested name, reason, and callback details and creates a **Follow-up Case** without disclosing employee availability or direct contact numbers.
_Avoid_: Customer asking for account manager by name for their own account service, internal employee call routing, published employee directory lookup

**Contact Reason**:
The classified purpose of an inbound external interaction used for case routing and response selection, such as customer account service, government, supplier, staffing, sales outreach, named recipient request, non-customer general, or unknown.
_Avoid_: Free-form note only, channel label, profile name, required perfect classification before reply

**Non-Customer General**:
The **Contact Reason** used when inbound traffic is clearly **Non-Customer Contact** but does not confidently match a preset sub-reason such as government, supplier, or staffing.
_Avoid_: Unmatched Caller, customer account service, improvised Hermes policy

**Standard Non-Customer Intake**:
The governed intake script for **Non-Customer Contact** traffic that collects caller identity, organization, reason, and callback details without account disclosure or employee directory lookup.
_Avoid_: Free-form AI response, Registered Phone recovery language, live transfer promise

**Contact Reason Uplift**:
An urgency upgrade applied from message content signals such as tax authority, invoice dispute, payroll, or safety language, even when the preset **Contact Reason** label is uncertain.
_Avoid_: Manual supervisor-only urgency, keyword spam escalation, customer-account urgency rules

**Low-Risk Customer Service Action**:
A customer-facing action Hermes may complete without changing accounting, refunds, pricing, inventory, or delivery commitments.
_Avoid_: Admin action, account adjustment

**Follow-up Case**:
A **Human Intervention Case** record created when Hermes should not complete a customer request automatically and an employee must review or resolve it in the **Copilot Workbench**.
_Avoid_: Auto-handled conversation log, audit-only thread, separate helpdesk system

**Human Intervention Case**:
A case marked as requiring employee action in the **Copilot Workbench**, including standard and **Urgent Follow-up Case** items.
_Avoid_: Auto-handled external turn, audit-only conversation

**Auto-Handled Interaction**:
An external customer-service turn that the **External Customer Service Profile** completes without opening a **Human Intervention Case**. Hermes still records it for audit and traceability.
_Avoid_: Copilot queue item, employee-required review, silent untracked conversation

**Urgent Follow-up Case**:
A **Follow-up Case** flagged for priority review because of billing dispute, emotional escalation, safety sensitivity, or repeated tool failure with continued customer pressure.
_Avoid_: Routine order lookup, every unmatched caller, promised response deadline

**Tool Unavailable Response**:
The external customer-service behavior when a live business tool fails: state temporary unavailability in brief English, create a **Follow-up Case**, and do not fabricate order, accounting, delivery, or payment facts.
_Avoid_: RAG guess, cached answer as live status, silent failure

**Textline Webhook Verification**:
The required authenticity check for inbound Textline webhook requests before Hermes processes an SMS event.
_Avoid_: Unsigned webhook acceptance, client-side API secrets

**After-Hours Service**:
Customer-service coverage provided by the **External Customer Service Profile** when Net2phone routes a call to Hermes outside normal live-staff coverage.
_Avoid_: 24/7 live support, always-on human queue, Hermes-defined schedule

**Always-On SMS Service**:
The first-version Textline SMS mode in which Hermes auto-replies 24/7 through the **External Customer Service Profile**, independent of Net2phone routing schedules.
_Avoid_: Business-hours SMS silence, live-staff SMS preemption in MVP

**SMS Opt-Out**:
A customer request sent via **STOP**, **UNSUBSCRIBE**, or **ARRET** that stops marketing and proactive outbound texts to that phone number while preserving governed service replies to customer-initiated inquiries.
_Avoid_: Opt-out of all inbound support, proactive STOP disclaimer on every reply

**SMS Opt-Out Confirmation**:
The single brief English reply Hermes sends after processing an **SMS Opt-Out Keyword**, confirming marketing unsubscribe while noting that account-support texts remain available.
_Avoid_: Long explanation, repeated confirmations, support blackout

**SMS Opt-Out Keyword**:
An inbound Textline message containing **STOP**, **UNSUBSCRIBE**, or **ARRET** that triggers **SMS Opt-Out** handling and consent updates in the **Identity Graph**.
_Avoid_: Marketing footer, implied opt-out without keyword

**SMS Session**:
A Textline conversation window for one phone number that stays open for 24 hours after the latest inbound or outbound message and then closes.
_Avoid_: Permanent session, one-message session, voice call session

**SMS Session Timeout**:
The point at which an **SMS Session** closes after 24 hours without a new message. The next inbound text starts a new **SMS Session** and the **Channel Gateway** runs **Ingress Phone Match** again before agent processing.
_Avoid_: Customer-facing re-verification prompt, carrying prior-session verified state without re-lookup
_Avoid_: Automatic forever-verified customer, shared session across phone numbers

**Hermes Transfer Rule**:
A Net2phone configuration set by the operations department that automatically transfers calls to the Twilio Hermes line, including after-hours and no-answer routing in the first version.
_Avoid_: Hermes routing engine, Twilio schedule, IVR AI menu in first version

**After-Hours Transfer Rule**:
A **Hermes Transfer Rule** that routes calls to Hermes during off-hours periods defined by operations in Net2phone.
_Avoid_: Hermes-defined schedule, business-hours knowledge used for routing

**No-Answer Transfer Rule**:
A **Hermes Transfer Rule** that routes calls to Hermes when the live-staff queue rings without answer.
_Avoid_: Voicemail as default, Hermes polling Net2phone queue state

**After-Hours MVP Scenario**:
A first-version customer request type that Hermes may handle during **After-Hours Service**.
_Avoid_: Full service catalog, unrestricted support topic

**Live Handoff**:
A real-time transfer from Hermes to a human employee during an active conversation.
_Avoid_: Follow-up Case, callback promise

**English-Only Phone Service**:
The first-version limit that the **External Customer Service Profile** handles phone conversations in English only.
_Avoid_: Bilingual phone AI, French phone knowledge path, automatic French transfer in MVP

**English-Only External Service**:
The first-version language limit for customer-facing Hermes channels, including **Text-First Launch** on Textline SMS and the later **Voice Layer**.
_Avoid_: Bilingual customer AI, French knowledge path in MVP

**Non-English Caller**:
A phone caller who speaks a language outside **English-Only Phone Service**; Hermes collects basic contact details and creates a **Follow-up Case** instead of continuing in that language.
_Avoid_: Verified Customer with full service, French AI conversation

**Launch Eval Gate**:
The required pre-launch evaluation suite that Hermes must pass before the phone MVP goes live, and again after material model, prompt, or policy changes. The minimum suite includes customer-service, product-media, and non-customer inbound scenarios executed from repository YAML fixtures.
_Avoid_: Ad hoc spot check, post-launch-only testing, customer-only regression, manual-only admin checklist

**Launch Eval Scenario**:
A versioned executable test definition for one **Launch Eval Gate** case, stored as a YAML fixture with inbound turns, mock tool responses, and standard behavioral, tool, disclosure, text, and severity assertions.
_Avoid_: Informal test note, live-only integration script, text-only pass/fail without case or tool checks

**Launch Eval Runner**:
The CLI process that executes **Launch Eval Scenario** fixtures against the **External Customer Service Profile**, merges `eval/mocks/base.yaml` with per-scenario `mock_overrides`, writes a standard JSON eval report to `eval/reports/`, and records eval-run results for `toee_eval_review`.
_Avoid_: Manual chat spot check, production customer traffic test, unlogged eval execution, per-scenario full mock duplication, exit-code-only eval output

**Launch Eval Report**:
The standard JSON artifact produced by the **Launch Eval Runner** for one eval run, including scenario results, severity summary, and model, prompt, and knowledge versions.
_Avoid_: Informal test log, undocumented pass/fail note, report without scenario-level failures

**Policy Publish Eval Suite**:
The targeted **Launch Eval Scenario** set used when operational policy is submitted for publish, composed of slot-mapped scenario ids from `eval/policy_slot_map.yaml` plus regression scenarios 2, 7, and 8.
_Avoid_: Full launch eval on every typo, manually chosen scenario list, publish without eval linkage

**Email Link Failure**:
A state where a **Verified Customer** cannot be linked from Shopify to QBO because the Shopify email is missing or has no matching **QBO Customer**.
_Avoid_: Accounting lookup failure, partial verification

**Payment Link**:
A secure Square-hosted link sent to a customer so they can pay without sharing card details with Hermes.
_Avoid_: Card collection, phone payment

**SMS Payment Link Reply**:
A **Payment Link** sent only as a reply in the current verified Textline conversation thread to the customer's Shopify **Registered Phone**.
_Avoid_: New SMS thread, alternate contact from message body, email fallback from SMS request in MVP

**Registered Contact**:
An existing phone number or email already stored on the matched Shopify Customer record.
_Avoid_: Verbal contact request, temporary contact

**Shopify Customer**:
The customer record in Shopify used for orders, contact data, and phone-based verification.
_Avoid_: QBO customer, caller

**QBO Customer**:
The customer record in QuickBooks Online used for invoices, balances, and accounts receivable.
_Avoid_: Shopify customer, caller

**Identity Graph**:
The mapping layer in **Hermes Native Memory** that links channel identities, **Session Identity Snapshot** records, business-system customer records, consent state, match history, cross-channel identity relationships, and **Customer Memory** binding keys.
_Avoid_: CRM, customer database, verification state only in ephemeral agent context, merged Copilot timeline in v1, storing SMS opt-out as a preference slot

**Sender Identity Intake**:
The synchronous sender lookup the **Channel Gateway** performs on inbound email before agent processing, capturing sender address, display name, and stated organization and running **Email Sender Match** for session identity.
_Avoid_: Mid-thread email verification ceremony, phone-match assumptions on email, improvised sender trust without lookup

**Email Sender Match**:
The first-version email identity check that treats the authenticated inbound **From** address matching a Shopify Customer **Registered Email** as sufficient for **Verified Customer** access on the email channel, completed during **Sender Identity Intake** at message receipt.
_Avoid_: Multi-factor verification, Reply-To matching, body-supplied alternate email matching, domain-only match

**Registered Email**:
The email address stored on a Shopify Customer record used for **Email Sender Match** on the email channel and as the **Customer Email Link** to **QBO Customer**.
_Avoid_: Any sender address, reply-to override from message body, personal inbox not on the customer record

**Email Thread**:
The long-lived inbound email conversation record in **Hermes Native Memory** for an authenticated sender **From** identity, spanning multiple inbound messages without a 24-hour timeout.
_Avoid_: One-message email log, channel-only mailbox outside Hermes, SMS-style 24-hour session cutoff

**Customer Email Link**:
The email address used as the sole cross-system identifier between a **Shopify Customer** and a **QBO Customer**.
_Avoid_: Phone match, company-name match

**Data Retention Policy**:
The governed retention periods Hermes applies to recordings, transcripts, conversation turns, **Customer Memory**, cases, audit logs, and knowledge version history.
_Avoid_: Indefinite storage by default, ad hoc deletion

**Customer Deletion Request**:
A customer request to remove or restrict stored conversation and account-related records; in the first version this is handled through a manual cross-system process.
_Avoid_: Automatic erasure, single-button delete

## Relationships

- **Hermes VA** has one **Hermes Core**.
- **Hermes Core** is not a separately invented Gemini-style application core; it is the shared Hermes text orchestration layer reused across profiles and channels.
- **Cloud-Hosted Hermes** runs on Google Cloud Run and adds Google Cloud services only as **Hermes Core** requirements demand.
- The repository is a polyglot monorepo: the Python `hermes/` package holds the `toee_hermes` Hermes plugin (**Domain Adapter Tools**, **Tool Gate**, profiles) and the **Launch Eval Runner**; the Python `hermes-runtime/` package holds the **Channel Gateway** (FastAPI) and the Hermes library embedding; `apps/workbench` is the Next.js workbench with its supporting `packages/*` TypeScript libraries.
- `apps/workbench` uses the Next.js App Router with `(public)` and `(authenticated)` route groups mapping directly to `/login`, `/copilot`, `/copilot/audit/*`, and `/admin/*`.
- `apps/workbench` authenticates with an HttpOnly session cookie, protects authenticated pages and BFF routes through middleware, and derives `internal_copilot` versus `supervisor_admin` profile context from `/copilot` and `/admin` route prefixes.
- `apps/workbench` exposes resource-oriented BFF routes under `/api/auth`, `/api/copilot`, and `/api/admin` that map internally to v1 **Domain Adapter Tools** without exposing raw tool envelopes to the browser. Per ADR-0141 those handlers reach the backend over HTTP — deterministic `POST /v1/tools:dispatch` for resource reads/writes and the agent-turn API for chat/drafts — not an in-process TypeScript executor.
- The **Channel Gateway** is the Python FastAPI Cloud Run service in `hermes-runtime/` with `POST /webhooks/textline` and a server-side pipeline for verification, normalization, ingress phone match, and **External Customer Service Profile** execution that embeds Hermes via the Python library (ADR-0139). The legacy Node Fastify `services/hermes-gateway` is superseded and retained only as historical scaffolding.
- There is no TypeScript in-process Hermes SDK (ADR-0139): Hermes is the upstream Python `hermes-agent`, embedded only by the Python integration layer. `apps/workbench` never imports Hermes; it reaches the **Internal Copilot Profile** and **Supervisor Admin Profile** through the per-profile Hermes HTTP API (ADR-0141: deterministic `POST /v1/tools:dispatch` running `execute_tool` for resources, plus the OpenAI-compatible agent-turn API for chat/drafts; bearer auth per profile).
- The Python Hermes packages (`hermes/`, `hermes-runtime/`) build with `uv` against the upstream `hermes-agent` pinned by git rev (the ADR-0101 pin-and-eval-gate workflow, now against the rev). `apps/workbench` and its supporting `packages/*` TypeScript libraries use a pnpm workspace.
- Local development runs the workbench with pnpm and the Python gateway with `uv` (no Docker by default); production deploys separate Cloud Run services from `apps/workbench/Dockerfile` and `hermes-runtime/Dockerfile` (ADR-0098 env layering still applies; the gateway image path is updated per ADR-0139). See `docs/ops/deploy-cloud-run.md`.
- Toee Tire memory for **Hermes VA** lives in **Hermes Native Memory**, not a parallel custom store.
- External systems connect through the **Hermes Integration Surface** using Skills, Tools, and MCP.
- Customer-service policy boundaries are enforced through **Tool Gate** checks and **Hermes Profile** tool allowlists, with **Skill Guidance** and **Launch Eval Gate** as supporting layers.
- The **External Customer Service Profile** uses a default-deny **Profile Tool Allowlist** of Toee Tire **Business Integration Tool** reads plus restricted **Hermes Built-in Tools** such as `web_search`.
- The **External Customer Service Profile** does not register terminal, browser, write, Copilot, or campaign tools in the first version.
- The **Internal Copilot Profile** may use broader read and case tools than the external profile, but does not register business-system write tools in the first version.
- **Copilot Draft Action** is in scope for v1; other **Copilot Governed Write** phases beyond employee-confirmed Textline send remain future ADR decisions.
- **Auto-Handled Interaction** threads are audit-recorded but do not enter the default Copilot work queue.
- Only **Human Intervention Case** items use **Copilot Gateway** for employee drafting in v1.
- The default **Operations Dashboard** queue for **Customer Service Rep** users shows **Human Intervention Case** items only, excluding **Contact Reason** `sales_outreach` cases.
- Other non-customer **Human Intervention Case** items appear in the same default queue as customer cases and may be filtered by **Contact Reason** and urgency.
- **Workbench Supervisor** and **Workbench Admin** users may use the read-only **Sales Outreach Audit View** to sample `sales_outreach` **Follow-up Case** records.
- **Workbench Supervisor** and **Workbench Admin** users may use the read-only **Auto-Handled Audit View** to sample **Auto-Handled Interaction** records.
- Opening an auto-handled thread or sales-outreach audit case writes a **Workbench Audit Log** entry.
- When handling a **Human Intervention Case**, employees see read-only **Case Thread Context** for the active channel thread only in v1, including prior **Auto-Handled Interaction** turns on that channel.
- The **Identity Graph** may record cross-channel identity links, but the default **Copilot Workbench** does not merge SMS, email, and voice history into one timeline in the first version.
- Opening or refreshing **Case Thread Context** writes a **Workbench Audit Log** entry.
- The first **Copilot Governed Write** phase is employee-confirmed Textline send from an editable draft card and confirmation modal inside a claimed **Human Intervention Case** on an active **SMS Session**.
- The **Supervisor Admin Profile** governs knowledge, eval review, and workbench administration, but does not register customer-facing send or business write tools in the first version.
- **Workbench Supervisor** and **Workbench Admin** users use two separate entry points: **Copilot Workbench** on the **Internal Copilot Profile** and the **Admin Governance Console** on the **Supervisor Admin Profile**.
- The **Admin Governance Console** uses three routes in v1: `/admin/knowledge`, `/admin/eval`, and `/admin/accounts`.
- Every authorized **Workbench Account** lands on `/copilot` after login.
- **Customer Service Rep** users see only Copilot navigation; **Workbench Supervisor** and **Workbench Admin** users also see top-level links to `/admin/knowledge`, `/admin/eval`, and `/admin/accounts`.
- `/admin/knowledge` uses a master-detail layout with six **Required Operational Policy Slot** statuses and slot-editor actions for save draft, submit for eval, and rollback published.
- `/admin/eval` uses a master-detail layout with eval run list rows and report detail for scenario results, medium-failure sign-off, and pending-policy promotion.
- `/admin/accounts` uses a table-first layout with create and role-edit drawer or modal forms and confirmed disable actions.
- The workbench global shell exposes a user menu with logout, enforces the 8-hour inactivity timeout with an expiry modal, and shows a dismissible global error banner for blocking API or adapter failures.
- **Customer Service Rep** users receive only the **Copilot Workbench** entry in the first version.
- `toee_identity_lookup` v1 actions are `match_phone`, `match_email_sender`, and `get_email_link_status`.
- `match_phone` and `match_email_sender` run at channel ingress before external agent processing; `get_email_link_status` supports accounting-read gating.
- `toee_shopify_read` v1 actions are `get_order`, `list_customer_orders`, `search_products`, and `get_product`.
- `get_order` and `list_customer_orders` require a **Verified Customer**; `search_products` and `get_product` allow **Unmatched Caller** public-catalog access with account-scoped fields removed by **Tool Gate**.
- `toee_qbo_read` v1 actions are `get_invoice`, `list_customer_invoices`, and `get_ar_summary`.
- All `toee_qbo_read` actions require a **Verified Customer** and a successful **Customer Email Link**; **Email Link Failure** blocks accounting reads.
- `toee_easyroutes_read` v1 actions are `get_delivery_status` and `get_route_details`.
- `toee_easyroutes_read` actions require a **Verified Customer** and a matched customer order reference.
- `toee_case` v1 actions are `create_case` and `update_case` for external **Follow-up Case** creation and limited urgency or **Contact Reason** updates.
- `toee_textline_reply` v1 action is `send_message` for the current **SMS Session**, with optional `media_url` for **Product Media Reply**.
- `toee_square_payment_link` v1 action is `send_payment_link` for a verified current-thread **Payment Link** only.
- `toee_knowledge_search` v1 actions are `search_public_site` and `search_operational_policy`.
- `search_operational_policy` returns only **Published Operational Policy** content for external and Copilot use.
- `toee_copilot_draft` v1 actions are `draft_sms`, `draft_email`, and `draft_internal_note` on the **Internal Copilot Profile**.
- `toee_case_manage` v1 actions are `claim_case`, `assign_case`, `update_priority`, `update_contact_reason`, and `resolve_case` on the **Internal Copilot Profile**.
- `toee_workbench_read` v1 actions are `get_case`, `list_cases`, `get_audit_log`, and `get_thread` on the **Internal Copilot Profile** and **Supervisor Admin Profile**.
- `toee_knowledge_ops` v1 actions are `get_policy_slots`, `update_policy_slot`, `submit_for_eval`, and `rollback_published_policy` on the **Supervisor Admin Profile**.
- `toee_eval_review` v1 actions are `list_eval_runs`, `get_eval_run`, `sign_off_medium_failure`, and `promote_pending_policy` on the **Supervisor Admin Profile**.
- `toee_workbench_admin` v1 actions are `list_accounts`, `create_account`, `update_account_role`, and `disable_account` on the **Supervisor Admin Profile**.
- `match_phone` and `match_email_sender` run at channel ingress before external agent processing; `get_email_link_status` supports accounting-read gating.
- Tooe Tire **Domain Adapter Tools** expose v1 behavior through fixed per-tool **Domain Adapter Tool Action** enums selected by a required `action` parameter.
- Shopify, QBO, Square, EasyRoutes, Textline, and Twilio connect through **Business Integration Tool** layers in the first version, not third-party or self-hosted MCP wrappers.
- Weekly **Knowledge Crawl** runs as a scheduled Hermes Skill using the native web crawl stack; **Scrapling** is only a **Crawl Fetch Fallback**, not the primary crawl path.
- Toee Tire business rules are implemented as thin **Domain Adapter** layers on top of **Hermes Core**, not by porting the Gemini VA application core.
- Textline is a **channel** into the **External Customer Service Profile**, not a separate **Hermes Profile**.
- Hermes stores a long-lived **Customer Thread** per Textline phone number and one or more bounded **SMS Session** windows inside it.
- The **Channel Gateway** verifies Textline webhooks and routes normalized events into **Hermes Core** under the external profile.
- Employees use the **Internal Copilot Profile** through the **Copilot Gateway** inside the **Copilot Workbench**.
- The **Operations Dashboard** reads case and conversation state from **Hermes Native Memory**.
- The first-version **Copilot Workbench** uses a split layout: **Operations Dashboard** on the left and **Copilot Gateway** on the right.
- The default **Copilot Workbench** route is `/copilot` with a dual-zone left **Operations Dashboard**: **Case Queue** and read-only **Case Thread Context** for the selected case.
- The **Case Queue** shows urgent flag, channel, identity summary, **Contact Reason**, last message preview, **Case Assignee**, status, last activity time, and tool-failure flag for each **Human Intervention Case** row.
- The default **Case Queue** sort is urgent first, then unassigned before assigned, then oldest open case first within each tier.
- **Customer Service Rep** users open `/copilot` with default filters for open or in-progress cases assigned to them or unassigned.
- **Workbench Supervisor** and **Workbench Admin** users use **Agent Workload View** as additional **Case Queue** filters on `/copilot`, including all-team assignee scope and optional resolved-case review.
- On `/copilot`, the **Copilot Gateway** shows an idle prompt until a **Human Intervention Case** is selected, then scopes draft and evidence actions to that case.
- On `/copilot/audit/auto-handled` and `/copilot/audit/sales-outreach`, the **Copilot Gateway** is hidden and the audit surface is read-only full width.
- Audit lists use shared columns for channel, identity or sender summary, preview, outcome or status, and last activity time; auto-handled rows add tool summary and tool-failure markers, and sales-outreach rows add case id, `sales_outreach`, and created time.
- Audit lists default to most recent activity first.
- Audit detail pages use a read-only summary header, conversation timeline, and route-specific evidence panel without draft or case-management controls.
- **Case Thread Context** uses a sticky header bar for case metadata and `toee_case_manage` actions, with a read-only highlighted timeline below.
- **Workbench Supervisor** and **Workbench Admin** users open read-only audit routes at `/copilot/audit/auto-handled` and `/copilot/audit/sales-outreach`; **Customer Service Rep** users do not receive those navigation entries in v1.
- Each human employee signs in with their own **Workbench Account**; case handling is attributed through **Case Assignee** and **Workbench Audit Log** entries.
- **Workbench Supervisor** users may use the **Agent Workload View** to see case ownership and resolution activity across the team.
- **Hermes Core** serves one or more **Hermes Profiles**.
- **Text-First Launch** goes live on Textline SMS before the **Voice Layer** is added.
- Textline SMS operates as **Always-On SMS Service**; Hermes auto-replies 24/7 in the first version.
- An **SMS Opt-Out Keyword** records **SMS Opt-Out** in the **Identity Graph** and blocks marketing or proactive outbound texts to that number.
- Hermes sends one **SMS Opt-Out Confirmation** after an **SMS Opt-Out Keyword** and does not add proactive STOP marketing disclaimer text to normal customer-service SMS replies.
- Textline SMS uses a **24-hour SMS Session** window per phone number.
- After **SMS Session Timeout**, the next inbound text starts a new **SMS Session** and the **Channel Gateway** runs **Ingress Phone Match** again before agent processing.
- **Ingress Phone Match** completes **Phone Match Verification** at message receipt; customers do not receive a separate verification ceremony.
- Each **SMS Session** stores a **Session Identity Snapshot** in the **Identity Graph** for tool authorization and audit.
- A new **SMS Session** begins with an **SMS Session Opener** in the first reply; later replies in the same session do not repeat the full opener.
- When a live business tool fails, Hermes uses a **Tool Unavailable Response** instead of fabricating account or order facts.
- Inbound Textline webhooks must pass **Textline Webhook Verification** before Hermes handles an SMS event.
- **After-Hours Service** applies to Net2phone-routed voice calls, not to the Textline SMS auto-reply schedule.
- The **Voice Layer** reuses the same **Hermes Core** validated during **Text-First Launch**; it does not fork a separate customer-service brain.
- **External Customer Service Profile**, **Internal Copilot Profile**, and **Supervisor Admin Profile** are **Hermes Profiles**.
- **Voice Gateway** provides audio input and output for the **External Customer Service Profile**.
- **Voice Gateway** may deliver a **Personalized Opening Greeting** before Hermes begins the conversation.
- **Opening Greeting** uses one script framework for all Net2phone transfers; it does not vary by after-hours versus no-answer routing.
- The first-version external channels operate under **English-Only External Service**, including **Text-First Launch** on Textline SMS.
- A **Non-English Caller** on phone receives a brief English explanation, basic intake, and a **Follow-up Case** rather than full AI service in another language.
- **Launch Eval Gate** scenarios 1–18 execute from repository YAML fixtures through the **Launch Eval Runner** with mock **Domain Adapter** responses for Text-First go-live.
- Each **Launch Eval Scenario** includes at minimum one behavioral or tool assertion, one disclosure or text assertion, and a `max_severity` value.
- **Launch Eval Runner** merges shared `eval/mocks/base.yaml` with per-scenario `mock_overrides` before executing a scenario.
- **Launch Eval Runner** writes a standard JSON **Launch Eval Report** to `eval/reports/` for `toee_eval_review`.
- Go-live and publish promotion are blocked when a **Launch Eval Report** has any high-severity failures.
- **Knowledge Publish Eval Gate** runs the **Policy Publish Eval Suite** from `eval/policy_slot_map.yaml` plus regression scenarios 2, 7, and 8.
- The phone MVP cannot launch until scenarios 1–18 pass with no high-severity failures.
- Email channel go-live reruns the email fixture subset, including scenarios 14–18 and 19–23, through the same **Launch Eval Runner**.
- When an email channel is added after **Text-First Launch**, inbound email uses the same **External Customer Service Profile**, **Contact Reason** rules, non-customer playbooks, and **Sales Outreach Audit View** routing as SMS and voice.
- **Email Thread** agent runtime context continues across replies from the same authenticated sender without a 24-hour timeout.
- Each inbound email message runs **Sender Identity Intake** and **Email Sender Match** on the authenticated **From** address before agent processing.
- Every Hermes outbound email includes the same fixed **Email Support Signature** governed by published operational policy.
- A **Verified Customer** on email is identified when the authenticated **From** address matches a Shopify Customer **Registered Email**.
- A request to continue verified email service on a different address supplied in **Reply-To** or message body creates a **Follow-up Case**.
- An **Ambiguous Email Match** requires customer disambiguation before Hermes treats the sender as a **Verified Customer** for account-scoped requests on the email channel.
- Email channel go-live reruns non-customer scenarios on email fixtures and adds email customer-identity scenarios for verified, unmatched, and non-customer traffic.
- **Text-First Launch** on Textline SMS must pass the **Launch Eval Gate** before go-live; the **Voice Layer** and later email channel each require a subsequent eval pass.
- A **Personalized Opening Greeting** may include company or contact name and account recognition, but must follow the **Greeting Personalization Boundary**.
- **KnowledgeOps** controls what approved knowledge the **Hermes Core** can use.
- **Public Site Knowledge** is rebuilt weekly before go-live through **Shopify Knowledge Sync** as the primary source and **Tavily Gap Crawl** as the supplement.
- **Knowledge Crawl** still governs **Approved Crawl URL** scope; Tavily fetches only gap URLs not already indexed by Shopify sync.
- **Operational Policy Knowledge** remains internally governed and is not replaced by website content alone.
- Hermes maintains six **Required Operational Policy Slots** as **Operational Policy Placeholder** records from onboarding onward.
- An unfilled **Required Operational Policy Slot** triggers **Knowledge Gap Prompt** questions to authorized **Supervisor Admin Profile** users until **KnowledgeOps** publishes approved content.
- Hermes does not improvise operational policy answers when a **Required Operational Policy Slot** has no approved content.
- **Operational Policy Knowledge** becomes customer-effective only after it passes the **Knowledge Publish Eval Gate** and is promoted to **Published Operational Policy**.
- Failed publish attempts remain **Pending Eval Knowledge** while the prior **Published Operational Policy** version stays active externally.
- The **Knowledge Publish Eval Gate** applies to **Operational Policy Knowledge** only, not to weekly **Shopify Knowledge Sync** or **Tavily Gap Crawl** updates to **Public Site Knowledge**.
- Hermes answers policy and FAQ-style questions from **Public Site Knowledge**, but answers account-specific facts from tools and governed operational rules.
- A **Verified Customer** is identified through **Phone Match Verification** against a Shopify Customer **Registered Phone** on voice and Textline SMS.
- **Phone Match Verification**, unmatched handling, ambiguous match handling, and **Payment Link** rules are shared across Textline SMS and voice.
- Hermes merges customer context by phone number in the **Identity Graph** across SMS and voice sessions.
- A **Verified Customer** may receive all **External Customer Service Profile** read access and **Low-Risk Customer Service Actions** for the matched Shopify Customer.
- An **Unmatched Caller** receives no account information disclosure and may receive public-catalog help such as **Product Media Reply** without account-scoped facts.
- A **Non-Customer Contact** with **Contact Reason** `sales_outreach` receives a brief decline and always creates a low-priority **Follow-up Case** for audit sampling in the **Sales Outreach Audit View**, not the default rep queue.
- A **Non-Customer Contact** with **Contact Reason** `named_recipient_request` receives message intake only; Hermes creates a **Follow-up Case** without disclosing employee availability or direct contact numbers.
- When an inbound party is not a **Verified Customer**, Hermes classifies **Contact Reason** from the first external message or spoken utterance.
- If first-message intent is ambiguous, Hermes asks one neutral clarification question with zero account disclosure before choosing **Unmatched Caller** or **Non-Customer Contact** handling.
- A **Follow-up Case** for either an **Unmatched Caller** or a **Non-Customer Contact** records a **Contact Reason** for **Copilot Workbench** routing.
- A **Non-Customer Contact** with **Contact Reason** `government` receives **Standard Non-Customer Intake** and creates an **Urgent Follow-up Case** by default.
- A **Non-Customer Contact** with **Contact Reason** `supplier` creates a normal-priority **Follow-up Case**, unless invoice, accounts-payable, delivery, or shipment language triggers **Contact Reason Uplift** to urgent.
- A **Non-Customer Contact** with **Contact Reason** `staffing` creates a normal-priority **Follow-up Case**, unless payroll, wage dispute, safety, or harassment language triggers **Contact Reason Uplift** to urgent.
- When preset **Contact Reason** mapping is uncertain but traffic is clearly non-customer, Hermes uses **Contact Reason** `non_customer_general` and **Standard Non-Customer Intake** rather than improvising a new response policy.
- **Contact Reason Uplift** may still mark a `non_customer_general` case urgent when high-risk content signals are present.
- An **Ambiguous Phone Match** requires customer disambiguation before Hermes treats the caller as a **Verified Customer**.
- A **Shopify Customer** links to a **QBO Customer** only through the **Customer Email Link**.
- Hermes uses the matched **Shopify Customer** email to resolve the corresponding **QBO Customer** for accounting reads.
- An **Email Link Failure** allows Shopify order and delivery answers, but blocks QBO accounting disclosure and creates a **Follow-up Case**.
- A request outside **Low-Risk Customer Service Action** boundaries creates a **Follow-up Case**.
- Hermes marks an **Urgent Follow-up Case** for billing disputes, emotional escalation, safety-sensitive issues, or repeated tool failure with continued pressure.
- **Urgent Follow-up Case** items are prioritized in the **Copilot Workbench** without promising a specific response time.
- A **Payment Link** is a **Low-Risk Customer Service Action** only when it does not require Hermes to handle card details.
- A **Payment Link** may be sent only to a **Registered Contact** on the matched Shopify Customer.
- A **Product Media Reply** may be sent to an **Unmatched Caller** for public catalog products, but must not include account-scoped pricing, inventory, or order context.
- A **Verified Customer** may receive live price and inventory in the same **Product Media Reply** when requested, using live Shopify Tool reads only.
- A **Prior Order Product Reference** may be resolved for a **Verified Customer** only when recent Shopify order history uniquely identifies one product; otherwise Hermes asks for order number, invoice number, or size.
- An **Unmatched Caller** may not use a **Prior Order Product Reference**.
- A **Product Media Reply** sends at most one product per reply; ambiguous product requests require disambiguation before sending.
- A **Product Media Reply** falls back to a public product page link when MMS delivery is unavailable or fails.
- On Textline SMS, a **Payment Link** is sent only as an **SMS Payment Link Reply** in the current verified thread.
- A verbal or text request to send a **Payment Link** to a new phone number or email creates a **Follow-up Case**.
- During **After-Hours Service**, Hermes does not perform a **Live Handoff** and instead creates a **Follow-up Case** for the next business day.
- The first version of **After-Hours Service** supports only approved **After-Hours MVP Scenarios**.
- **After-Hours Transfer Rules** are configured in Net2phone by the operations department; Hermes does not define or enforce the after-hours routing schedule.
- **Hermes Transfer Rules**, including **After-Hours Transfer Rules** and **No-Answer Transfer Rules**, are configured only in Net2phone by the operations department.
- A call reaches **After-Hours Service** when Net2phone transfers it to the Twilio Hermes line under those rules.
- Employees review **Follow-up Cases** in the **Copilot Workbench** through the **Internal Copilot Profile**.
- **Customer Service Rep**, **Workbench Supervisor**, and **Workbench Admin** are the only default roles with **Copilot Workbench** access in the first version.
- Sales, warehouse, finance, and other non-customer-service roles have no default **Copilot Workbench** access.
- **Copilot Workbench** access in the first version requires a provisioned **Workbench Account** with username and password authentication.
- **Workbench Account** access follows the **Workbench Password Policy**.
- **Case Resolution** in the first version is human-driven; Copilot may draft responses but not execute accounting or payment write actions.
- Hermes applies a **Data Retention Policy** by data class for recordings, transcripts, cases, audit logs, and knowledge version history.
- A **Customer Deletion Request** is handled manually across systems in the first version.

## Example dialogue

> **Dev:** "Should the phone AI answer billing questions directly?"
> **Domain expert:** "The **External Customer Service Profile** can answer only after verification and only from approved knowledge or read-only accounting tools."

> **Dev:** "Can customer calls train Hermes?"
> **Domain expert:** "No. Calls can create review items, but **KnowledgeOps** decides what becomes approved knowledge."

> **Dev:** "How do we verify a customer on the after-hours phone line?"
> **Domain expert:** "If the inbound phone number matches a Shopify Customer **Registered Phone**, that caller is a **Verified Customer** through **Phone Match Verification**."

> **Dev:** "What if the caller's phone does not match?"
> **Domain expert:** "If they are asking for customer account, order, or billing help, they are an **Unmatched Caller**. Hermes discloses no account data, may still help with public-catalog requests, and may suggest calling back from a Toee Tire **Registered Phone** for account access."

> **Dev:** "What if a government agency, supplier, or temp worker contacts us?"
> **Domain expert:** "That is a **Non-Customer Contact**, not an **Unmatched Caller**. Hermes still discloses no customer account data, but uses non-customer intake language, records a **Contact Reason** such as government, supplier, or staffing, and creates a **Follow-up Case** for internal routing."

> **Dev:** "What about salespeople pitching services or someone asking for a specific employee?"
> **Domain expert:** "Both are **Non-Customer Contact** cases. **Sales Outreach** gets a brief decline and always creates a low-priority **Follow-up Case** for audit sampling. **Named Recipient Request** collects who they want, why, and how to reach them, then creates a **Follow-up Case** without saying whether that person is available or giving internal or personal numbers."

> **Dev:** "What if we cannot tell whether someone is government, supplier, or something else we did not list?"
> **Domain expert:** "Hermes only needs to get the primary fork right: customer-service path versus **Non-Customer Contact**. If the sub-reason is unclear, it uses **Contact Reason** `non_customer_general`, runs **Standard Non-Customer Intake** from published operational policy, and creates a **Follow-up Case**. That is governed intake, not free-form improvisation. **Contact Reason Uplift** can still mark the case urgent when the message mentions tax, invoice dispute, payroll, or safety issues."

> **Dev:** "Can employees fix the category later?"
> **Domain expert:** "Yes. **Copilot Workbench** users may recategorize **Contact Reason** on the case without changing zero-account-disclosure rules."

> **Dev:** "What if the first text is just 'Hi' or intent is unclear?"
> **Domain expert:** "Hermes asks one brief neutral clarification question, still with zero account disclosure. If intent stays unclear, it creates a **Follow-up Case** with **Contact Reason** unknown."

> **Dev:** "What if one phone matches multiple Shopify customers?"
> **Domain expert:** "That is an **Ambiguous Phone Match**. Hermes asks for disambiguation such as company name, order number, or invoice number. If still ambiguous, it creates a **Follow-up Case**."

> **Dev:** "After verification, can Hermes adjust an overdue invoice?"
> **Domain expert:** "No. Even for a **Verified Customer**, adjusting accounting is not a **Low-Risk Customer Service Action**; Hermes should create a **Follow-up Case**."

> **Dev:** "How does Hermes connect Shopify and QBO for AR questions?"
> **Domain expert:** "Only through the **Customer Email Link**. Phone verification identifies the **Shopify Customer**; Hermes then uses that customer's email to find the **QBO Customer**."

> **Dev:** "What if the Shopify email is missing or has no QBO match?"
> **Domain expert:** "That is an **Email Link Failure**. Hermes may still answer Shopify order and delivery questions, but accounting answers are blocked and a **Follow-up Case** is created."

> **Dev:** "Can Hermes text a payment link to a number the caller gives on the phone?"
> **Domain expert:** "No. A **Payment Link** may be sent only to a **Registered Contact** on the matched Shopify Customer. A new contact request creates a **Follow-up Case**."

> **Dev:** "Can after-hours callers reach a live human?"
> **Domain expert:** "No. During **After-Hours Service**, Hermes does not perform a **Live Handoff**. It creates a **Follow-up Case** for the next business day."

> **Dev:** "Where do employees handle those cases the next morning?"
> **Domain expert:** "In the **Copilot Workbench** through the **Internal Copilot Profile**. They review the case, see the summary and tool results, draft replies, and perform **Case Resolution** manually in source systems."

> **Dev:** "Should every caller hear the same opening message?"
> **Domain expert:** "No. The **Opening Greeting** should be a **Personalized Opening Greeting** based on the inbound phone number and matched Shopify Customer context."

> **Dev:** "Can the greeting mention an overdue balance?"
> **Domain expert:** "No. The **Greeting Personalization Boundary** allows company or contact name and account recognition, but not invoice amounts, balances, or overdue details in the opening."

> **Dev:** "Can we use toeetire.com as the only knowledge source?"
> **Domain expert:** "Not alone. **Public Site Knowledge** is refreshed by weekly **Knowledge Crawl** into a local index, but **Operational Policy Knowledge** must stay internally governed because website pages do not encode Hermes verification, payment-link, and after-hours rules."

> **Dev:** "How often should Hermes refresh website knowledge?"
> **Domain expert:** "Weekly **Knowledge Crawl** is enough for public policy and FAQ. Supervisors can trigger an extra rebuild after major policy changes."

> **Dev:** "Can Hermes crawl every page on toeetire.com?"
> **Domain expert:** "No. **Knowledge Crawl** only fetches **Approved Crawl URL** pages from the sitemap, such as pages, policies, blogs, and product education content. It excludes cart, checkout, account, login, and dynamic search URLs."

> **Dev:** "What if we launch before all internal policy rules are written?"
> **Domain expert:** "Hermes still creates all six **Required Operational Policy Slots** as **Operational Policy Placeholder** records. If a slot is empty, Hermes sends **Knowledge Gap Prompt** questions to **Supervisor Admin Profile** users until **KnowledgeOps** publishes approved content. Hermes does not improvise that policy for customers."

> **Dev:** "How long do we keep call recordings and audit logs?"
> **Domain expert:** "Under the **Data Retention Policy**, recordings and transcripts are kept for 90 days, **Follow-up Cases** and session summaries for 2 years, tool audit logs for 7 years, and published knowledge version history is retained for rollback. A **Customer Deletion Request** is handled manually in the first version."

> **Dev:** "Does Hermes decide when after-hours starts?"
> **Domain expert:** "No. **Hermes Transfer Rules** live in Net2phone and are set by operations. When Net2phone transfers a call to Hermes, that conversation is handled through the **External Customer Service Profile**. Hermes may answer published business hours for customers, but it does not control routing."

> **Dev:** "Who configures no-answer transfer to Hermes?"
> **Domain expert:** "Operations, in Net2phone. A **No-Answer Transfer Rule** is a **Hermes Transfer Rule**, same as after-hours routing. Hermes only handles calls that Net2phone has already transferred."

> **Dev:** "Should no-answer calls get a different opening greeting than after-hours calls?"
> **Domain expert:** "No. Hermes uses one **Opening Greeting** framework for every Net2phone transfer. **Personalized Opening Greeting** varies only by Shopify phone-match context, not by transfer trigger."

> **Dev:** "Can Hermes handle French phone calls in the first version?"
> **Domain expert:** "No. Phone MVP is **English-Only Phone Service**. A **Non-English Caller** gets a short English explanation, basic intake, and a **Follow-up Case** for human follow-up."

> **Dev:** "Can we launch phone MVP without a full test pass?"
> **Domain expert:** "No. The **Launch Eval Gate** must pass first, and it must be rerun after material model, prompt, or policy changes."

> **Dev:** "If a supervisor submits one operational policy slot, do we rerun all 18 launch scenarios?"
> **Domain expert:** "No. **Knowledge Publish Eval Gate** runs the **Policy Publish Eval Suite** mapped in `eval/policy_slot_map.yaml` for that slot, plus regression scenarios 2, 7, and 8. Full scenarios 1–18 are still required for initial Text-First go-live."

> **Dev:** "How does Admin review an eval run?"
> **Domain expert:** "The **Launch Eval Runner** writes a JSON **Launch Eval Report** under `eval/reports/`. **Supervisor Admin** reads it through `toee_eval_review.get_eval_run`. Any high-severity failure blocks promotion; medium failures may be signed off."

> **Dev:** "Do we duplicate Shopify and QBO mock data in every eval scenario?"
> **Domain expert:** "No. Shared data lives in `eval/mocks/base.yaml`, and each **Launch Eval Scenario** only declares `mock_overrides` for the differences that scenario needs."

> **Dev:** "What does each launch eval scenario have to assert?"
> **Domain expert:** "At minimum one behavioral or tool assertion, one disclosure or text assertion, and a `max_severity`. High-severity failures block go-live; medium failures may be signed off in `toee_eval_review`."

> **Dev:** "How do we run launch eval before go-live?"
> **Domain expert:** "From versioned YAML **Launch Eval Scenario** fixtures under `eval/scenarios/`, executed by the **Launch Eval Runner** against the **External Customer Service Profile** with mock adapters. Text-First requires scenarios 1–18."

> **Dev:** "Does the launch eval suite cover non-customer inbound traffic?"
> **Domain expert:** "Yes. Minimum scenarios 14–18 cover government default urgent, supplier invoice uplift, sales outreach low-priority case, named recipient non-disclosure, and non-customer general governed fallback without improvised policy."

> **Dev:** "Can every employee use Copilot Workbench?"
> **Domain expert:** "No. Only **Customer Service Rep**, **Workbench Supervisor**, and **Workbench Admin** have default access. Other roles do not see **Follow-up Cases** unless explicitly granted later."

> **Dev:** "Should we launch phone before SMS?"
> **Domain expert:** "No. **Text-First Launch** on Textline SMS comes first so identity, tools, knowledge, and policy issues surface on text. The **Voice Layer** is added after that path is stable."

> **Dev:** "Does SMS use different identity rules than phone?"
> **Domain expert:** "No. **Phone Match Verification** is shared. The Textline sender number and the inbound call number both match against Shopify **Registered Phone** with the same verified, unmatched, and ambiguous outcomes."

> **Dev:** "Is Hermes only on SMS after business hours?"
> **Domain expert:** "No. Textline uses **Always-On SMS Service** in the first version. Hermes auto-replies 24/7. **After-Hours Service** applies to Net2phone-routed voice, not SMS hours."

> **Dev:** "Should every Hermes SMS include a STOP disclaimer?"
> **Domain expert:** "No. Hermes handles **SMS Opt-Out** only when the customer sends an **SMS Opt-Out Keyword** such as STOP, UNSUBSCRIBE, or ARRET. Normal service replies do not include proactive marketing opt-out footer text."

> **Dev:** "What should Hermes say after a customer texts STOP?"
> **Domain expert:** "Hermes sends one brief **SMS Opt-Out Confirmation** in English, then stops marketing or proactive outbound texts. The customer can still text back later for account support."

> **Dev:** "How do employees sign in to Copilot Workbench?"
> **Domain expert:** "Through a provisioned **Workbench Account** with username and password. A **Workbench Admin** creates accounts and assigns roles in the first version."

> **Dev:** "If a customer texts again the next day, does Hermes remember verification?"
> **Domain expert:** "Only inside an open **SMS Session**. After **SMS Session Timeout** at 24 hours, the next text starts a new session. The **Channel Gateway** runs **Ingress Phone Match** again before the agent turn, but this is silent to the customer—no separate verification prompt."

> **Dev:** "When is Phone Match Verification complete for an inbound SMS?"
> **Domain expert:** "At message receipt. **Ingress Phone Match** runs in the **Channel Gateway** before **Hermes Core** processes the text, and the result is stored as the current **Session Identity Snapshot**. Customers never go through a standalone verify-your-identity step."

> **Dev:** "What if Shopify is down during an SMS order lookup?"
> **Domain expert:** "Hermes uses a **Tool Unavailable Response**: say the system is temporarily unavailable, create a **Follow-up Case**, and never fabricate order or accounting facts from RAG."

> **Dev:** "Can we skip Textline webhook verification in MVP?"
> **Domain expert:** "No. Every inbound Textline webhook must pass **Textline Webhook Verification** before Hermes processes the SMS event."

> **Dev:** "Can Hermes text a payment link to a different number if the customer asks in SMS?"
> **Domain expert:** "No. On Textline, a **Payment Link** must be an **SMS Payment Link Reply** in the current verified thread to the **Registered Phone**. A new contact request creates a **Follow-up Case**."

> **Dev:** "When should an SMS case be marked urgent?"
> **Domain expert:** "When it becomes an **Urgent Follow-up Case**: billing dispute, emotional escalation, safety sensitivity, or repeated tool failure with continued pressure. Routine lookups stay normal priority."

> **Dev:** "Does SMS need an opening message like phone?"
> **Domain expert:** "Not a voice **Opening Greeting**, but each new **SMS Session** starts with an **SMS Session Opener** in the first reply. Later texts in the same session do not repeat it."

> **Dev:** "Do we provision PostgreSQL and Redis on day one?"
> **Domain expert:** "Not by default. **Cloud-Hosted Hermes** runs on Cloud Run and activates Google Cloud services only when **Hermes Core** capabilities require them."

> **Dev:** "Can we copy Gemini VA modules into Hermes?"
> **Domain expert:** "No. Build on **Hermes Core** with **Hermes Native Memory** and the **Hermes Integration Surface** via Skills, Tools, and MCP. Gemini VA is reference material for business rules, not a code port source."

> **Dev:** "Can supervisors see which agent handled which case?"
> **Domain expert:** "Yes. Each action is attributed through **Case Assignee** and **Workbench Audit Log** entries in **Hermes Native Memory**. Supervisors use the **Agent Workload View** to review ownership and resolution activity."

> **Dev:** "Should Shopify and QBO go through MCP?"
> **Domain expert:** "No. They connect through **Business Integration Tool** adapters in the first version. There is no official MCP server to trust, and a self-hosted MCP would duplicate Hermes audit and profile controls."

> **Dev:** "How does weekly website crawl run?"
> **Domain expert:** "A scheduled **Knowledge Crawl** Skill uses Hermes native web crawl with Tavily as the primary backend, sitemap discovery per **Approved Crawl URL** rules, and **Crawl Fetch Fallback** through cloud browser providers or an isolated crawl job—not local desktop Chrome CDP on Cloud Run."

> **Dev:** "Does Cloud-Hosted Hermes support local Chrome CDP for crawl?"
> **Domain expert:** "Not in production. `/browser connect` CDP is for a browser on the same machine as the operator, typically local development. On Cloud Run, browser fallback uses Hermes cloud browser providers; Scrapling runs only inside a dedicated crawl job if needed."

> **Dev:** "Can Shopify Admin API replace website crawl entirely?"
> **Domain expert:** "No. **Shopify Knowledge Sync** is the primary **Public Site Knowledge** source before go-live, but **Tavily Gap Crawl** still indexes approved URLs Shopify did not cover, and live product images use **Product Media Reply** through the Shopify Tool."

> **Dev:** "Can Hermes text a product photo from last week's knowledge index?"
> **Domain expert:** "No. A **Product Media Reply** must resolve the image through a live Shopify Tool read in the **current SMS Session**."

> **Dev:** "Can an unmatched SMS number receive a tire product photo?"
> **Domain expert:** "Yes, if it is public catalog media only. **Product Media Reply** may go to an **Unmatched Caller**, but must not include account-scoped pricing, inventory, or order context."

> **Dev:** "Can a verified customer get price and stock in the same product-photo SMS?"
> **Domain expert:** "Yes. A **Verified Customer** may receive live price and inventory in the same **Product Media Reply**, but those facts must come from live Shopify Tool reads, not RAG."

> **Dev:** "What if a verified customer asks for a photo of the tire they ordered last time?"
> **Domain expert:** "Hermes may resolve a **Prior Order Product Reference** from recent Shopify order history only when one product is uniquely identified. If multiple recent orders could match, Hermes asks for an order number, invoice number, or size first."

> **Dev:** "If we write all rules in Skills, will Hermes always follow them?"
> **Domain expert:** "No. **Skill Guidance** is not enforcement. Critical rules must be implemented as **Tool Gate** checks and profile tool allowlists, with **Launch Eval Gate** regression tests to catch drift."

> **Dev:** "Where is the full v1 tool action list documented?"
> **Domain expert:** "In ADR-0070. Each tool uses one integration surface with fixed `action` enums, and **Tool Gate** enforces profile and identity rules per action."

> **Dev:** "How are Shopify and QBO exposed to Hermes?"
> **Domain expert:** "As **Domain Adapter Tools** such as `toee_shopify_read` with fixed **Domain Adapter Tool Action** enums like `get_order` or `search_products`. **Tool Gate** enforces which actions each profile may call."

> **Dev:** "Are our Shopify tools different from Hermes native tools?"
> **Domain expert:** "They are **Domain Adapter Tools** registered on the same Hermes tool surface as **Hermes Built-in Tools**. The **External Customer Service Profile** exposes only its **Profile Tool Allowlist**."

> **Dev:** "Can Copilot send payment links or edit QBO in v1?"
> **Domain expert:** "No for payment links, QBO writes, or other business-system writes. v1 **Internal Copilot Profile** supports **Copilot Draft Action**, case workflow, and phase 1 **Copilot Governed Write** for employee-confirmed Textline send inside a claimed **Human Intervention Case** only."

> **Dev:** "Does every SMS conversation need Copilot review?"
> **Domain expert:** "No. **Auto-Handled Interaction** turns stay audit-only. Only **Human Intervention Case** items enter the Copilot queue for drafting or later confirmed send."

> **Dev:** "Does the email signature change for verified customers?"
> **Domain expert:** "No. **Email Support Signature** uses one fixed published line for every outbound email. Company recognition belongs in the message body when needed, not in the signature."

> **Dev:** "Does email need an opener like SMS?"
> **Domain expert:** "No. Email uses a brief **Email Support Signature** on every outbound message instead of an **SMS Session Opener**-style first-reply introduction. The signature text is governed operational policy, not improvised."

> **Dev:** "Does email use the same 24-hour session window as SMS?"
> **Domain expert:** "No. Email uses **Email Thread** continuity for conversation context. Each inbound message still reruns **Email Sender Match** silently on the authenticated **From** address, but Hermes does not force a 24-hour timeout like **SMS Session**."

> **Dev:** "Can Hermes verify a customer from a Reply-To or an email address written in the message body?"
> **Domain expert:** "No. **Email Sender Match** uses only the authenticated inbound **From** address after **Channel Gateway** verification. Alternate addresses in **Reply-To** or the body do not change identity and create a **Follow-up Case** if the customer asks to switch channels."

> **Dev:** "What if one sender email matches multiple Shopify customers?"
> **Domain expert:** "That is an **Ambiguous Email Match**. Hermes records the ambiguous state at message receipt and asks for disambiguation such as company name, order number, or invoice number only when account-scoped facts are requested. If still ambiguous, it creates a **Follow-up Case**."

> **Dev:** "How is a customer verified on email?"
> **Domain expert:** "Through **Email Sender Match** during **Sender Identity Intake**. If the inbound sender address matches a Shopify Customer **Registered Email**, the sender is a **Verified Customer** at message receipt with no separate verification ceremony."

> **Dev:** "When we add email later, do non-customer rules change?"
> **Domain expert:** "No. Email uses the same **External Customer Service Profile**, **Contact Reason** taxonomy, playbooks, and **Sales Outreach Audit View** routing. Only the ingress identity step changes to **Sender Identity Intake** instead of **Ingress Phone Match**. Email go-live reruns the non-customer **Launch Eval Gate** scenarios on email fixtures."

> **Dev:** "Do sales-outreach cases flood the Copilot queue?"
> **Domain expert:** "No. `sales_outreach` **Follow-up Case** records go to the read-only **Sales Outreach Audit View** for **Workbench Supervisor** and **Workbench Admin** sampling. They do not appear in the default **Operations Dashboard** queue for reps. Other non-customer cases such as government, supplier, or named recipient requests stay in the main queue and may be filtered by **Contact Reason**."

> **Dev:** "Can supervisors review auto-handled SMS threads?"
> **Domain expert:** "Yes, through the read-only **Auto-Handled Audit View**. Rep default queues still show **Human Intervention Case** items only, and viewing a thread there is logged in the **Workbench Audit Log**."

> **Dev:** "When a rep opens a human-intervention case, do they see only that case's messages?"
> **Domain expert:** "No. They see read-only **Case Thread Context** for the full active channel thread, including earlier **Auto-Handled Interaction** turns on that channel. Cross-channel SMS, email, and voice history is not merged in the v1 **Copilot Workbench** UI."

> **Dev:** "If a customer texts yesterday and emails today, does Copilot show one merged timeline?"
> **Domain expert:** "Not in v1. **Case Thread Context** stays channel-specific. The **Identity Graph** may link the identities in the background, but reps do not get one combined timeline across channels yet."

> **Dev:** "Can Supervisor Admin send Textline replies to customers?"
> **Domain expert:** "No in v1. The **Supervisor Admin Profile** manages **KnowledgeOps**, eval review, and workbench administration. Customer replies stay in the **External Customer Service Profile** or **Human Intervention Case** Copilot workflows."

> **Dev:** "Does a supervisor use one Hermes profile for everything?"
> **Domain expert:** "No. Supervisors use **Copilot Workbench** on the **Internal Copilot Profile** for case work and the **Admin Governance Console** on the **Supervisor Admin Profile** for knowledge and eval governance."

> **Dev:** "If a supervisor publishes a new operational policy slot, does it go live immediately?"
> **Domain expert:** "No. It stays **Pending Eval Knowledge** until the **Knowledge Publish Eval Gate** passes. Only then does it become **Published Operational Policy** for the **External Customer Service Profile**."

> **Dev:** "Does weekly Shopify knowledge sync also need publish eval?"
> **Domain expert:** "No. The **Knowledge Publish Eval Gate** applies to **Operational Policy Knowledge** only. **Public Site Knowledge** rebuilds from **Shopify Knowledge Sync** and **Tavily Gap Crawl** follow the weekly rebuild rules without a separate publish-eval step."

## Flagged ambiguities

- "Hermes" can mean **Hermes VA** as the whole system or **Hermes Core** as the text orchestration layer; resolved: use **Hermes VA** for the system and **Hermes Core** for the shared text brain.
- "Profile" means a governed **Hermes Profile**, not a separate deployed assistant.
- "Verified" means **Phone Match Verification** against Shopify, not manual identity proof.
- "Full permissions" for a **Verified Customer** means full external-profile access for that matched customer, but still excludes accounting changes, refunds, discounts, and other non-low-risk actions.
- **Registered Phone** is expected to be unique in Shopify, but **Ambiguous Phone Match** handling remains required as a backup control.
- **Customer Email Link** is the only approved cross-system customer identifier between Shopify and QBO.

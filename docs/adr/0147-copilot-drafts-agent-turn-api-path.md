# Copilot reply drafts generate over a per-profile agent-turn API, not tools:dispatch

> **Status: Accepted** (2026-06-26). Promoted from Proposed after the Slice 1
> tracer (commit `8fbc4a0`) landed and passed review (verdict: approve). The forks
> below are resolved as recommended (A1/B1/C1/D1/E1). Realizes the drafts half of
> Slice 36 (#39) and resolves the #41 deferral; built incrementally per the sliced
> plan below.
>
> **Slice 1 review amendments (accepted):**
> 1. **No-auto-send is pinned by allowlist-equality, not a two-tool denylist.** The
>    tracer asserted only that two named send tools were absent; the invariant is
>    now *the booted tool set equals the `internal_copilot` allowlist* (plus a
>    frozen reviewed-snapshot tripwire), so adding **any** toolset to the profile
>    breaks the test and forces re-review (see Governance frame; `test_copilot_turn`).
> 2. **`draft_generated` audit moves server-side in Slice 3.** The sub-fork's
>    "revisit when the audit store cuts over" trigger has arrived: audit-log reads
>    and case-mutation writes are already server-side, so a BFF-written
>    `draft_generated` is now *write-only in API mode*. Recording it server-side is
>    scheduled for Slice 3 (with the real-provider endpoint); **not** implemented in
>    the Slice 1–2 increment (see the sub-fork below).

## Context

Increment 3 of the local-first migration (#38) cut the Copilot **case mutations**
(`claim`/`assign`/`resolve`/`priority`/`contact-reason`) onto the deterministic
`POST /v1/tools:dispatch` path (ADR-0141), but **stop-and-reported on drafts**
(#41): per ADR-0141 copilot drafts are a *genuine agent turn* (LLM), not a
deterministic resource write, so they belong on the **agent-turn API**, which does
not yet exist. Cutting drafts onto `tools:dispatch` would contradict ADR-0141.

**How a draft works today (the parity contract).** The flow is *generate-and-display*,
with no persisted draft entity:

- **BFF** `handleDraft` (`apps/workbench/lib/bff/copilot/drafts.ts`): validates a
  selected `caseId` (400 missing, 404 unknown), calls the **in-process TypeScript
  mock** `executeTool({ tool: "toee_copilot_draft", action, params: { caseId, prompt } })`
  (`@toee/domain-adapters`), and on success writes a `draft_generated` audit with
  `detail = <action>` and returns `{ draft: <toolData> }`. Tool failure → 502, **no
  audit**.
- **Three thin Next routes** (`app/api/copilot/drafts/{sms,email,note}/route.ts`)
  wrap it with `withSession`, one per `DraftAction`
  (`draft_sms`/`draft_email`/`draft_internal_note`).
- **Tool shapes** (the mock, `packages/domain-adapters/src/mock/admin-stubs.ts` and
  the Python mirror `hermes/toee_hermes/drivers/mock/admin_stubs.py`):
  SMS `{ channel:"sms", draft }`, email `{ channel:"email", subject, draft }`, note
  `{ kind:"internal_note", draft }` — canned strings, **no LLM** on either runtime.
- **UI** `components/copilot/CopilotGateway.tsx`: a returned draft string fills an
  **editable textarea** (`draftBody`); the employee may edit it, then — only on an
  SMS case with an active session they hold (ADR-0083) — open `GovernedSendModal`.
- **Becoming outbound** is a *separate, decoupled* governed write
  (`lib/bff/copilot/messages.ts` `handleTextlineSend`): it takes **free-text `body`**
  (the edited draft, not a draft id), re-checks eligibility (400/404/403), calls
  `toee_textline_reply.send_message`, mirrors the message into the thread, and audits
  `textline_send`. There is **no drafts store, no draft id, and no link** from a
  draft to a send — the draft is ephemeral client state.

So "drafts" today = a stubbed string + a `draft_generated` audit. The deferred work
is to make generation a **real agent turn (LLM)** while preserving that exact BFF
surface (404/400/502 statuses, `draft_generated`/`detail` audit, `{ draft: {channel,
draft} }` body).

**What agent-turn plumbing already exists (and for whom).** A real `AIAgent` turn is
already built — but only for the **External** Textline pipeline:

- `hermes-runtime/hermes_runtime/live.py` `run_agent_turn(...)` drives a **real Nous
  `run_agent.AIAgent`** loop, forced non-streaming, capturing `{final_response,
  messages}`. Its `openai_factory` parameter is **the one model boundary**: inject a
  **scripted** client for deterministic tests (`run_scripted_agent`, no
  network/key), or pass `None` to use the real OpenAI client pointed at a base URL.
  It boots a profile (`boot_profile`) so scripted/real tool calls dispatch through
  **real governed execution** (catalog → Tool Gate → driver → audit).
- `hermes-runtime/hermes_runtime/openrouter.py` `make_openrouter_run_turn(...)` is the
  **production** boundary: resolves OpenRouter creds (ADR-0009: `OPENROUTER_API_KEY`,
  primary `deepseek/deepseek-v4-pro`, fallback `qwen/qwen3.6-flash`), wraps the
  factory with per-completion fallback, boots **External bound to a `conversation_id`**
  (ADR-0107), and runs the turn.
- `hermes-runtime/hermes_runtime/turn_runner.py` + `gateway_app.py`: the External turn
  runs **async** off a Cloud Tasks job (`POST /internal/jobs/agent-turn`, ADR-0105/0106),
  reloads the inbound context (ADR-0107), and delivers the reply via governed
  `toee_textline_reply`.

**The gap for copilot drafts** is therefore narrow and specific:

1. The per-profile server (`hermes-runtime/hermes_runtime/tool_dispatch_app.py` +
   `tool_dispatch_composition.py`) is **deterministic-only** — `POST /v1/tools:dispatch`,
   explicitly "no LLM". It has **no agent-turn route**.
2. The agent-turn machinery is wired only for the **External** profile, **bound** to a
   Textline conversation, **async**, and ending in a **send**. Copilot drafts need the
   **`internal_copilot`** profile, **unbound** (no conversation), **synchronous**, and
   ending in **proposed text, never a send**.
3. The BFF drafts path calls the **in-process TS mock**; there is no HTTP agent client
   and no `handleDraftViaApi`.

**Governance frame (load-bearing).** Drafts are **proposals**, never sends
(ADR-0067: "Draft actions never send to customers or write business systems"). The
`internal_copilot` **Profile Tool Allowlist** (ADR-0035, default-deny ADR-0034)
**already excludes** `toee_textline_reply` and `toee_square_payment_link`. So a draft
agent booted under `internal_copilot` **structurally cannot send** — the send tool is
never registered. No-auto-send is enforced by the existing profile allowlist, not a
new guard. Confirmed sends remain the separate, human-initiated ADR-0083/0036 path.

> **Amendment (Slice 1 review).** The invariant is pinned as **allowlist-equality**,
> not the tracer's initial two-tool denylist: `test_copilot_turn` asserts the booted
> tool set **equals** `allowlisted_tools(internal_copilot)` and that this allowlist
> equals a frozen reviewed snapshot. So a denied send tool is caught (it is outside
> the allowlist), *and* adding any new toolset to the profile — send-capable or not —
> trips the test and forces re-review, rather than silently widening a draft agent's
> reach. The channel never reaches `boot_profile`, so the booted set (and thus this
> invariant) is channel-independent across sms/email/internal_note.

## Decision (recommended; forks below are vetoable)

Add the **agent-turn capability** ADR-0141 already named ("Agent-turn API — serves
chat + drafts… the Hermes embedded `AIAgent` run under the same profile"), scoped to
the smallest thing that makes drafts real, reusing the External precedent verbatim
where possible.

1. **New route on the *same* per-profile server: `POST /v1/agent:turn`.** It lives
   beside `tools:dispatch` in the per-profile process (one `HERMES_HOME`, one bearer,
   one port — ADR-0141 "two capabilities behind one per-profile deployment"; ADR-0142
   local-first), but is a **distinct route**, keeping the deterministic dispatch app
   LLM-free. AIP-136 custom method, like `tools:dispatch`. Same bearer auth
   (constant-time, fail-closed 401) and same `actor_account_id` body field as dispatch
   (ADR-0141 actor attribution).
   - **Request:** `{ "channel": "sms"|"email"|"internal_note", "case_id": str,
     "prompt"?: str, "actor_account_id"?: str }`.
   - **Response:** the same governed envelope as dispatch — `{ "ok": true, "data": {
     "channel", "draft", "provenance": { "model", "profile" } } }`, or `{ "ok": false,
     "error": { "class", "message" } }` on a governed failure (HTTP 200; ADR-0020/0104).
     Auth/shape problems are 4xx (parity with `tool_dispatch_app`).
   - **Amendment (Slice 3 review, M3): the mount is INTERNAL-only.** Although the route
     boots `internal_copilot` regardless of host profile, the composition root
     (`tool_dispatch_composition.build_tool_dispatch_app`) mounts it **only when the
     server's profile is `internal_copilot`** — "the copilot server" (Fork A1). The
     SUPERVISOR/EXTERNAL per-profile dispatch servers expose `tools:dispatch` but
     **not** `agent:turn` (POST → 404), so the LLM draft surface cannot be reached on a
     server that should never draft, and the deterministic dispatch app stays LLM-free
     on every profile. No behavior change for the copilot path.

2. **The endpoint runs an unbound `internal_copilot` agent turn; the draft is the
   agent's `final_response`.** It boots `internal_copilot` **unbound** (`boot_profile`
   with no `conversation_id` — the Copilot path the boot docstring already calls out),
   so the agent has the copilot **read** tools (`toee_workbench_read`, `toee_knowledge_search`,
   `toee_shopify_read`, `toee_qbo_read`, …) to gather case context itself, but **no send
   tool** (ADR-0035). The `channel` selects a **per-channel system message** (SMS = short
   plain reply; email = subject + body; internal note = staff-facing). The agent's
   `final_response` **is** the draft text — mirroring `outbound_reply_text` deriving the
   External reply from `final_response`. Reuse `run_agent_turn` + the `openai_factory`
   seam unchanged.

3. **Provider: real OpenRouter when keyed, deterministic local stub otherwise**
   (mock-first, ADR-0137; consistent with `select_tool_driver`/`TOOL_BACKEND`). A
   copilot `run_turn` mirrors `make_openrouter_run_turn` but boots `internal_copilot`
   **unbound**. When `OPENROUTER_API_KEY` is set → real OpenRouter (ADR-0009);
   when absent → a deterministic stub completion (a fixed/templated draft), so local
   dev and CI run **keyless**, exactly as the dispatch server runs against `MockDriver`
   without Postgres. Tests inject scripted completions via the existing seam.

4. **BFF: a `HermesAgentClient` + `handleDraftViaApi`, env-gated on the *same* copilot
   pair.** A small client (sibling to `HermesApiClient`, `lib/gateway/`) POSTs
   `agent:turn` with the bearer + baked-in `actor_account_id`, parses the governed
   envelope, and throws `HermesApiError` on transport/governed failure.
   `handleDraftViaApi` (in `drafts.ts`) keeps the store path's preconditions and, on
   success, writes the **`draft_generated` audit (`detail = <action>`)** and returns
   `{ draft: { channel, draft } }` — **store-path parity**. Errors map through the
   existing `hermesErrorToProblem` (ADR-0104). The three Next routes branch
   API-vs-store on `HERMES_COPILOT_API_URL`/`HERMES_COPILOT_API_TOKEN` (the same env as
   the case cutover — one server, two routes), falling back to the in-memory
   `handleDraft` when unset.

5. **Generate-only; no drafts table; no send.** The cutover preserves today's
   ephemeral model: no draft entity is persisted, no draft id is minted, and the send
   path is untouched. `toee_copilot_draft` stays the **BFF-facing channel selector +
   audit `detail`** (`draft_sms`/`draft_email`/`draft_internal_note`); its mock stub is
   left in place for the store-fallback path. Generation does not flow through
   `tools:dispatch` (honoring #41).

**Net new surface:** one Python route + one copilot `run_turn` (a thin
`internal_copilot`/unbound variant of `openrouter.py`) + one TS client + one
`handleDraftViaApi` + a 3-route env branch. No new tools, no new tables, no new
process, no schema migration.

## Open forks — resolve before build (each independently vetoable)

**A. Where the agent-turn endpoint lives.** *Recommend A1.*
- **A1 — second route on the existing per-profile server** (chosen). One process, one
  bearer, one port; reuses profile boot + actor attribution; matches ADR-0141's "two
  capabilities behind one deployment." Cost: the embedding venv (already has Hermes)
  loads the agent in the same process as deterministic dispatch.
- **A2 — separate copilot agent-turn process/port.** Cleaner dependency isolation
  (LLM heft off the dispatch process); cost: a second process, port, token, and
  `.env`/runbook entry per profile, for one route. Over-built for v1.
- **A3 — reuse the gateway's `/internal/jobs/agent-turn`.** Rejected: it is
  External-profile, **conversation-bound** (ADR-0107), **async** Cloud Tasks, and ends
  in a send — none of which fit an interactive, unbound, no-send copilot draft.

**B. Sync vs stream vs async.** *Recommend B1.*
- **B1 — synchronous request/response** (chosen). The UI sets `draftBody` once
  (`await draft(kind)`); drafts are short; an employee waiting a few seconds is fine.
  Smallest BFF/Next plumbing.
- **B2 — stream tokens (SSE)** into the textarea. Nicer UX; adds streaming plumbing
  through Next + BFF + the agent's forced-non-streaming path. Defer as an enhancement.
- **B3 — async job + poll** (the External pattern). Rejected for copilot: that exists
  only because Textline webhooks must fast-ack (ADR-0103); an interactive employee
  request has no such constraint, and polling adds a store + status surface.

**C. Real-LLM vs injectable provider with local stub.** *Recommend C1.*
- **C1 — reuse the `openai_factory` seam from `live.py`** (chosen): scripted client in
  tests/CI, deterministic stub locally when keyless, real OpenRouter when keyed. Zero
  new abstraction; already proven; already governs tool dispatch.
- **C2 — a new higher-level "DraftProvider" interface** returning plain text. Smaller
  per-call type, but duplicates `live.py`/`openrouter.py` and a second model boundary
  to keep in sync. Rejected (not lazy).

**D. Generate-only vs generate+persist.** *Recommend D1.*
- **D1 — generate-only, no persistence** (chosen). Matches today exactly; "store-path
  parity" (#41) means *not* adding a draft entity. Smallest diff. The **drafts data
  cutover is therefore not a prerequisite** — there is no draft data to move.
- **D2 — persist a `workbench_draft` row** (survives reload, listable, linkable to a
  send). Real product value, but a new table + schema migration + read model + its own
  ADR, and it changes the UX (drafts become first-class). A separable later decision;
  building it now widens the slice well past #41.

**E. Is the draft the agent's `final_response`, or a `toee_copilot_draft.draft_*` tool
result?** *Recommend E1.* (This is the subtlest fork — it reinterprets #41's "back
`toee_copilot_draft.draft_*` consistent with ADR-0067.")
- **E1 — draft = `final_response`** (chosen). The agent gathers context via its
  governed read tools and emits the draft as its final assistant message; the BFF's
  `channel` shapes the system message. `toee_copilot_draft` is **not** the generator —
  it survives only as the channel selector + audit `detail`. ADR-0067's "never sends"
  holds trivially (generation never sends). Simplest; mirrors the External reply
  derivation.
- **E2 — draft = a governed `toee_copilot_draft.draft_*` call the agent makes**, with a
  real datastore handler (literally "back the stub"). This routes generation *through a
  tool*, but the tool would only echo model text (it has nothing to compute), and it
  re-introduces `tools:dispatch`-shaped flow that #41 says drafts should avoid. Its one
  merit: a natural in-`HERMES_HOME` place to record the `draft_generated` audit row
  (see sub-fork below). Weigh against the double-routing.
- **Sub-fork — who records `draft_generated`.** Today the BFF writes it. Under E1 the
  BFF keeps writing it (parity, simplest). If/when the **audit log itself** is
  Postgres-backed and must be written server-side in one transaction, either (i) the
  `agent:turn` endpoint records it, or (ii) a thin deterministic `toee_copilot_draft`
  audit-only handler records it (the E2 merit, without E2 doing generation). Recommend
  **(BFF writes it) for the tracer**, revisit when the audit store cuts over.
  - **Amendment (accepted, Slice 1 review): the trigger has arrived — schedule the
    move for Slice 3.** Audit-log **reads** and case-mutation **writes** are already
    server-side (the #38 / ADR-0145/0146 cutovers), so the audit store the governed
    surface reads back is no longer the BFF's in-memory store. A BFF-written
    `draft_generated` is therefore **write-only in API mode**: it lands in a store the
    governed audit-log read won't consult, so it cannot be read back through the
    surface that now owns case audit. The fix is option (i) — the `agent:turn`
    endpoint records `draft_generated` (`detail = <action>`) in the same governed
    path, retiring the BFF write. This is **scheduled for Slice 3** alongside the
    real-provider endpoint work and **not implemented in the Slice 1–2 increment**:
    Slices 1–2 keep the BFF-written audit for store-path parity, accepting the
    write-only gap until Slice 3 closes it.

## Proposed sliced implementation plan (TDD + review-gate rhythm)

Each slice is independently green and reviewed, mirroring increments 4–7
(`c9f7d48`/`d8cb22b`/`81c1acd`/`1cdcb1b`). The first is a tracer bullet that proves the
**whole seam** with a deterministic provider — no real model, exactly as ADR-0141's
tracer proved `GET /api/copilot/cases` end-to-end against `MockDriver`.

- **Slice 1 — tracer bullet: the agent-turn seam, scripted provider, one channel.**
  - *Python:* add `POST /v1/agent:turn` to the per-profile app (bearer 401, shape 4xx),
    booting `internal_copilot` **unbound** and running a **scripted** `run_agent_turn`
    whose `final_response` becomes `data.draft`; wire it into
    `tool_dispatch_composition` so the existing copilot server serves both routes.
    Tests: bearer enforcement; an `internal_copilot` turn returns the scripted draft +
    provenance; a profile that lacks copilot tools is governed-denied; **no send tool is
    registered** (assert the booted tool set excludes `toee_textline_reply`).
  - *TypeScript:* a `HermesAgentClient` whose contract tests assert request shape
    (URL `/v1/agent:turn`, POST, `Authorization: Bearer`, body incl. `actor_account_id`)
    and envelope/error parsing against a fake `fetch`; `handleDraftViaApi` for **`sms`
    only**, env-gated, preserving 400/404, the `draft_generated` audit (`detail =
    "draft_sms"`), the `{ draft }` body, and ADR-0104 error mapping; the route falls
    back to the in-memory `handleDraft` when the copilot env pair is unset.
  - *Out of scope here:* real OpenRouter, email/note channels, streaming, persistence.
- **Slice 2 — all three channels + per-channel system messages.** Extend the endpoint
  and `handleDraftViaApi` to `email` (`{channel, subject, draft}`) and `internal_note`
  (`{kind, draft}`); assert shape parity with the mock for each; wire the `email`/`note`
  routes.
- **Slice 3 — real provider wiring (keyed) + governed context reads + server-side
  audit.** Add the copilot `run_turn` (OpenRouter when `OPENROUTER_API_KEY` present,
  ADR-0009; deterministic stub otherwise), and a scripted **tool-call** completion
  proving the agent pulls case/thread context via `toee_workbench_read` through real
  governed dispatch (catalog → gate → driver → audit). No real network in CI
  (scripted/stub). **Also record `draft_generated` server-side** here (the sub-fork
  amendment): the `agent:turn` endpoint writes the audit in the governed path,
  retiring the now write-only BFF audit.
  - **Build status (2026-06-26).** The real-model thirds **landed**: provider wiring
    keyed off `OPENROUTER_API_KEY` (real OpenRouter / deepseek primary + qwen
    fallback, keyless stub otherwise; provider injected so CI is keyless), the
    governed `toee_workbench_read` context-read proof (catalog → gate → driver, the
    read's result feeds back into a grounded draft), the multi-step **no-send
    rejection** proof (a scripted send `tool_call` is rejected by the real loop, not
    just at boot), and email **subject derivation** from `final_response` (the
    `Subject:`-first-line convention; deterministic fallback). The **server-side
    `draft_generated` audit is DEFERRED** to **#47** (`enhancement, ready-for-human`):
    it needs the sub-fork veto below (endpoint-direct vs the thin `toee_copilot_draft`
    audit-only handler) and reverses the intentional "`toee_copilot_draft` is not a
    datastore tool" contract; the BFF keeps writing its (write-only-in-API-mode)
    audit until #47 closes the gap.
  - **Build status (2026-06-27) — #47 closed via option (i) + review hardening.** The
    `agent:turn` endpoint now records `draft_generated` **server-side** through the
    *existing* datastore writer (`PostgresDriver.record_audit` → `insert_audit`, the
    same path the case-mutation cutover uses), attributed to the actor +
    `internal_copilot`, with `details.detail = <draft_sms|draft_email|draft_internal_note>`
    and `target_type='case'`/`target_id=<case_id>`, written in the datastore unit of
    work (a no-op sink in mock mode — no crash). `handleDraftViaApi` **stops** writing
    the in-memory `draft_generated` audit (the non-API `handleDraft` keeps its
    in-memory write), so there is **exactly one** `draft_generated` per successful
    API-mode draft and it surfaces via `toee_workbench_read.get_audit_log` (the
    cut-over audit-log view). Option **(ii)** (a thin `toee_copilot_draft` audit-only
    handler) was **not** taken — it would have reversed
    `test_unknown_datastore_tool_is_governed_configuration_missing`. Proven by
    `test_agent_turn_audit` (row on success per channel; none on a failed turn; read
    back via `get_audit_log`) and the updated `drafts.test.ts` (no API-path
    double-write). Slice 3 review **Minor** findings also resolved: **M3** — the
    `agent:turn` route is mounted **INTERNAL-only** (decision 1 amendment); **M2** — an
    empty `Subject:` line is stripped from the email body (deterministic fallback
    subject), so the bare line never leaks into the draft. **M1 (known gap, DEFERRED to
    #48):** `provenance.model` reports the *primary* model even when the per-completion
    fallback served — `model = resolved.model` is captured before the turn while the
    fallback swaps inside `make_fallback_openai_factory`, a wrapper the **External**
    profile turn shares, so threading the served model out has cross-profile blast
    radius beyond this increment. Tracked as a low-priority fidelity gap, not fixed here.
- **Slice 4 — `/api/copilot/chat` over the same endpoint (closes Slice 36 / #39).** Cut
  `handleChat` (today a deterministic stub) onto the same `agent:turn` route, reusing the
  draft-card path. (Optional within #41; listed because it reuses everything Slice 1–3
  build and finishes the agent-turn cutover.)
- **Later / separate ADRs:** persistence (Fork D2), streaming (Fork B2), the cloud
  slice (Slice 37 / #40: containerize the per-profile servers incl. the agent route,
  Secret Manager `OPENROUTER_API_KEY`), and the audit-store cutover sub-fork.

## Considered options

- **Put drafts on `tools:dispatch` with a real `toee_copilot_draft` handler
  (rejected).** Contradicts ADR-0141/#41: generation is a non-deterministic LLM turn,
  not a deterministic resource write; a tool handler cannot "generate" without an LLM
  behind it, which is exactly the agent-turn path.
- **A standalone copilot chat/draft microservice (rejected for v1).** Duplicates the
  profile/boot/governance the per-profile server already owns; reintroduces the
  profile/tool-drift ADR-0096/0139 avoid. The per-profile server already *is* the
  per-profile runtime.
- **Bind the copilot turn to a conversation like External (rejected).** ADR-0107
  binding exists to authorize an outbound **send** to the inbound conversation; a draft
  never sends, so binding adds nothing and would imply a send capability the profile
  must not have.
- **Build persistence now (deferred, Fork D2).** Larger than #41, changes the UX, needs
  its own schema + ADR.

## Verification

Design-only; nothing is implemented by this ADR. The Slice-1 tracer proves the contract
end to end with **no model**: bearer/shape enforcement on `POST /v1/agent:turn`; a
scripted `internal_copilot` unbound turn returning `{channel, draft, provenance}`; an
assertion that the booted copilot tool set **equals the `internal_copilot` allowlist**
(allowlist-equality — the governance invariant, hardened in the Slice 1 review from the
tracer's two-tool denylist); a `HermesAgentClient` contract test against a fake `fetch`; and an
env-gated `sms` draft route that preserves the `draft_generated` audit, the `{ draft }`
body, the 400/404/502 + ADR-0104 statuses, and the in-memory fallback. Subsequent
slices add channels, the real OpenRouter boundary (keyed; scripted/stub in CI), and the
chat cutover. No `tools:dispatch` change, no tool-catalog change, no migration.

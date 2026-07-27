# S02 — Lexicon decide/CRUD actions + console

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** T1 L7 Semantic Lexicon
- **Size:** M
- **Depends on:** S01
- **Delivers:** FR-3 (decide side), FR-8
- **Surface:** governed decide/CRUD actions; admin BFF routes; lexicon console

## ⚠ Pre-flight corrections — BINDING (see [../DECISIONS.md](../DECISIONS.md))

- **D7 — the edit either/or is WITHDRAWN. `edit` is an in-place UPDATE and the entry id is
  stable.** The Approach below offers "in-place UPDATE … or retire-old-then-write-new"; those
  are not interchangeable. They diverge on entry id stability, `hit_count` continuity, and on
  whether S09's `entry_ref`, S10's blast-radius join, and S26's per-entry health score survive
  an edit — shipping "either" guarantees one downstream join is wrong. In-place UPDATE, an
  `old → new` audit row, `hit_count` continues (an edited entry is the same entry).
  Retire-then-write stays available as the semantically different admin intent "that mapping
  was wrong, kill it and start a new one" — it is not an implementation choice for `edit`.
- **D0** — "S24's `_decide_experience`" below means **S24-0.0.3**, not the 0.0.5 S24.
- **D17** — you are the only catalog-touching slice in flight while you run.
- Declare your new actions in the `LAYER_OF_ACTION` map (0.0.5 S12) in this same diff, or the
  completeness test fails CI.

## Goal

FR-3/FR-8: the human gate — approve / edit / reject / retire / manual-add on lexicon entries,
all admin-only, plus the console (CRUD + detail surface; queue decisions later absorb into the
S15 inbox). US1: an admin adds "TOEE ≡ TOEE TIRE" live with no deploy. Exploration C1
§Governance.

## Approach

- Decide actions mirror S24's `_decide_experience` shared-UPDATE shape (only proposed rows
  transition; already-decided = safe no-op; decider framework-derived; no actor →
  `policy_blocked`); **mock+PG lockstep via ONE shared decision resolver** (NFR-7, gap-audit
  explicit); `edit` supersedes WITHOUT violating `UNIQUE(domain, surface_form)` — in-place
  UPDATE with an old→new audit row, or retire-old-then-write-new; either way both states are
  audited (gap-audit fix: a naive insert would collide); `manual-add` writes
  provenance=admin_manual directly to `confirmed` (admin IS the gate).
- ALL these actions in `_AGENT_EXCLUDED_ACTIONS` (never LLM-callable; verify via
  `registered_names()` tests — the house precedent).
- Admin BFF routes mirror `admin/agent-experience` (withSession/isAdminPath, actor from
  session); console = sibling of AgentExperienceConsole with a manual-add form.
- Confirmed-set version bump on every decide (feeds S05/S06 caches).

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** live-PG transitions with decider+decided_at; policy_blocked without actor;
  manual-add lands confirmed+admin_manual; edit supersedes with audit; exclusion tests green;
  vitest BFF routes; tsc clean.
- **② E2E (browser):** add an alias from the console → it lists as confirmed; retire it →
  status flips; screenshots.
- **③ Product (PAC):** PAC-2 — the owner adds/edits/retires an entry end-to-end.

## Out of scope

- Inbox presentation of the pending queue — **S15**. Application — **S05/S06**.

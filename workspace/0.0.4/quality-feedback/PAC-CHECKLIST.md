# quality-feedback — PAC checklist (NFR-1 layer ② / ③)

The four owner walkthroughs for the quality-feedback module, plus what an
automated run already proved.

**Status:** every PAC's *behaviour* has been executed against a live local stack
(real Next.js BFF → real dispatch server → real Postgres) and asserted by
reading the rows back out of Postgres. What remains for a human is the **browser
DOM layer** (clicking the controls) and the **simulator-driven** variant of the
PAC-1 subject — see [What is still owed](#what-is-still-owed).

---

## Bring the stack up

```bash
pnpm install
pnpm dev
```

`pnpm dev` starts Postgres, both dispatch servers (8091/8092), the gateway, both
workers, and the workbench on <http://localhost:3000>.

Seeded logins (from `0005_dev_bootstrap`, local dev only — password
`Workbench123!` for all three): `rep`, `supervisor`, `admin`.

> **No `OPENROUTER_API_KEY` needed.** Without one the runtime uses its
> deterministic keyless completion, so drafts still generate — canned, and
> therefore reproducible. Set a key only if you want live-model wording.

> **If `pnpm dev` fails with "container name already in use"**, a Postgres from
> another worktree owns the name. Stop that stack first (`docker compose down`
> in the other checkout). Alternatively run the app tier on the host against the
> already-running Postgres — see [Host-tier fallback](#host-tier-fallback).

---

## PAC-1 — score an auto-handled conversation

**Goal:** a supervisor can record a fail verdict with reason tags on an
auto-handled interaction, and it is attributed to them.

1. Sign in as **supervisor**.
2. Open **`/copilot/simulator`**. Pick the *verified customer* preset, send an
   inbound SMS the agent can answer on its own (e.g. *"Do you carry 225/65R17
   winter tires?"*). Wait for the reply in the thread.
   *(This is the step that needs the gateway + turn worker. It produces the
   auto-handled record PAC-1 scores.)*
3. Open **`/copilot/audit/auto-handled`** and click into that record.
4. In the review bar: click **Fail**. The external reason-tag chips expand.
5. Select **Factual error** and **Should have escalated**, type a comment, submit.

**Expect**
- [ ] The bar accepts the verdict; no error banner.
- [ ] Submit is refused until at least one tag is picked (fail requires a tag).
- [ ] The conversation itself is unchanged (audit views stay read-only).
- [ ] A `workbench_audit_log` row exists with action `interaction_review_submitted`
      and *your* account id.

---

## PAC-2 — sampling coverage is visible

**Goal:** the list shows what has already been sampled.

1. Go back to **`/copilot/audit/auto-handled`** (the list).
2. Find the record you just scored, and any other record.

**Expect**
- [ ] The scored record shows **Reviewed**.
- [ ] The other record still shows **Not reviewed**.
- [ ] Repeat on **`/copilot/audit/sales-outreach`** — its column behaves the same
      and a review on one list never marks a row on the other.

---

## PAC-3 — rate a copilot draft

**Goal:** a rep can say *why* a draft was wrong, in two clicks, without it ever
interfering with customer work.

1. Sign in as **rep**. Open `/copilot`, **claim** a case (feedback requires you
   to hold the case).
2. Click **Draft SMS**. A draft card appears.
3. Click **👎**. The internal reason-tag chips expand.
4. Pick **Too verbose** and **Wrong tone**, optionally comment, submit.

**Expect**
- [ ] 👍 submits immediately with no tag step; 👎 requires at least one tag.
- [ ] The chips are the *internal* set (`wrong_tone`, `too_verbose`, …) — the
      external set (`tone_inappropriate`, …) must NOT appear here.
- [ ] The draft stays editable and sendable throughout.
- [ ] **Rating failure never blocks the send:** the draft remains sendable even
      if the rating call errors.

---

## PAC-4 — the send outcome records itself

**Goal:** the highest-signal measurement costs the rep nothing.

1. On the same claimed case, generate a draft and **send it untouched**.
2. Generate another draft, **edit the text**, then send.

**Expect**
- [ ] Neither send shows any extra prompt — capture is silent.
- [ ] The untouched send records `sent_as_is` (no ratio).
- [ ] The edited send records `sent_edited` with an edit-distance ratio.
- [ ] A rating and an outcome for the *same* draft share one
      `draft_correlation_id` — two rows, one draft.
- [ ] **A failing capture never fails the send** — the customer's message goes
      out regardless.

---

## PAC-5 — governance (do this one deliberately)

- [ ] Sign in as **rep** and open `/copilot/audit/auto-handled` → access is
      refused. Reps cannot review; only supervisor/admin can.
- [ ] Feedback on a case you do **not** hold is refused.

---

## Verify the rows (optional, definitive)

```sql
SELECT subject_kind, subject_id, verdict, reason_tags, reviewer_account_id
FROM interaction_review ORDER BY created_at DESC LIMIT 5;

SELECT outcome, verdict, reason_tags, edit_distance_ratio, rep_account_id,
       draft_correlation_id
FROM draft_feedback ORDER BY created_at DESC LIMIT 5;
```

Both tables are **append-only** — re-reviewing appends a row, it never
overwrites. That is intended: the history of judgments is the audit trail.

---

## What an automated run already proved

Executed against a live stack (workbench 3000 → dispatch 8091/8092 → Postgres),
with every assertion made by reading the row back out of Postgres:

| Check | Result |
| --- | --- |
| PAC-1 review persists with tags, comment, framework-derived reviewer | PASS |
| PAC-1 `workbench_audit_log` row (`interaction_review_submitted`, correct actor) | PASS |
| PAC-2 list flips to Reviewed; sibling subject stays Not reviewed | PASS |
| PAC-3 rating persists `down` + both internal tags, attributed to the rep | PASS |
| PAC-4 `sent_edited` + ratio; rating and outcome share one correlation id | PASS |
| Rating row carries no ratio; outcome row carries no verdict | PASS |
| **Rep refused the review route (403)** | PASS |
| **No-actor write → `policy_blocked` AND zero rows, zero audit rows** | PASS |

The last two are the governance guarantees: the supervisor-only boundary exists
only at the BFF route gate, and *the AI cannot score itself* — a write with no
framework-resolved employee persists nothing.

### A real bug this run caught

`GET /api/copilot/audit/auto-handled` returned **HTTP 500** the moment a real
auto-handled record existed: `_build_auto_handled_record` returned
`last_activity_at` as a raw `datetime`, which is not JSON-serializable, so the
dispatch server's encode raised. Pre-existing (reconstructing the pre-S05 return
shape fails identically) and invisible until now because a fresh dev DB has no
auto-handled records at all — the list is always empty, so nothing ever
serialized. Fixed with the house `serialize_row` helper plus a regression test
that calls `json.dumps`, verified red-capable.

---

## What is still owed

1. **Browser DOM layer.** The checks above drove the real HTTP stack, not the
   rendered controls. Clicking the review bar, the thumbs chips, and the send
   modal still wants one human pass (the component behaviours are covered by 83
   workbench tests, but not the assembled page).
2. **Simulator-driven PAC-1 subject.** The automated run created its
   auto-handled record as a database fixture rather than by driving a
   conversation through the gateway. Step 2 of PAC-1 — a real simulated inbound
   producing a real auto-handled interaction — is the part to reproduce by hand.

---

## Host-tier fallback

If another worktree's Postgres owns the container name, run the app tier on the
host against the Postgres that is already up:

```bash
# migrations + demo accounts/cases into the running DB
cd hermes-runtime && HERMES_APPLY_DEV_SEED=1 uv run python -m hermes_runtime.datastore.migrate

# one per terminal (or backgrounded)
TOEE_HERMES_PROFILE=internal_copilot DISPATCH_API_TOKEN=dev-copilot-token TOOL_BACKEND=datastore \
  uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app --factory --host 127.0.0.1 --port 8091
TOEE_HERMES_PROFILE=supervisor_admin DISPATCH_API_TOKEN=dev-admin-token TOOL_BACKEND=datastore \
  uv run uvicorn hermes_runtime.tool_dispatch_composition:build_tool_dispatch_app --factory --host 127.0.0.1 --port 8092

pnpm dev:workbench   # from the repo root
```

This covers everything except the gateway-dependent simulator step (PAC-1 step 2).

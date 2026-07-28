# S30 — The external profile must actually open a case when it hands off

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** carry-in defect (found by the 0.0.4 quality-feedback acceptance run)
- **Size:** S-M
- **Depends on:** nothing in 0.0.5. **S31 should land first** — it is what makes this slice's
  fix provable rather than anecdotal.
- **Delivers:** no 0.0.5 FR — carry-in defect, see the README traceability note.
- **Surface:** `hermes/profiles/customer_service_external/SOUL.md`, eval scenarios, the
  escalation-rate read

## The evidence

Two conversations driven through the **real** stack during the 0.0.4 acceptance run (real
webhook → gateway → turn worker → live model), on a clean database:

| inbound | what the agent replied | `toee_case` called |
| --- | --- | --- |
| "What are your Saturday opening hours?" | *"I don't have our Saturday hours on hand at the moment, but I've asked the team to reach out to you directly."* | **no** |
| "I was charged twice on invoice 8891 and I need a refund today. This is urgent." | *"I can't pull up your account from this number, so…"* | **no** |

Neither opened a case. The first one is the sharper failure: the agent **told the customer a
human would follow up** and then created nothing for a human to see. Two for two, including an
urgent billing dispute from an unmatched caller — squarely a **Follow-up Case** by CONTEXT.md's
own definition ("created when Hermes should not complete a customer request automatically").

## Why it is not caught today

`SOUL.md` phrases the hand-off as prose, not as a tool contract:

- line 13 — "say so plainly and offer a follow-up or human hand-off"
- line 18 — "no-policy fallback and route to a human (ADR-0003)"

Nothing states that *the hand-off **is** a `toee_case` `create_case` call*, so "offer a
follow-up" is satisfiable — from the model's point of view — by saying the words. `toee_case`
is in the EXTERNAL Profile Tool Allowlist, so the capability was never the constraint.

## Why it matters more after 0.0.4 than before

Before the 0.0.4 gateway fix these conversations were merely invisible. Now they are worse
than invisible: with `auto_handled` written correctly, an un-escalated conversation is marked
**auto-handled** and appears in the Auto-Handled Audit View labelled **`auto_resolved`**. The
system now positively asserts *"the agent completed this on its own"* about a conversation the
agent abandoned mid-promise. The flag is not wrong — nothing escalated — but the reading a
supervisor takes from it is.

The quality-feedback loop does catch it: that first record was scored **fail /
`should_have_escalated`** by hand during the acceptance run, and `EXPLORATION.md` §Signal
Routing already routes `should_have_escalated` → L6 procedure proposal via **S25**. But that
path is *reactive* — it needs N=3 tagged reviews of *sampled* records before it proposes
anything. It closes the loop; it does not set the floor. This slice sets the floor.

## Approach

- Make the hand-off contract explicit in `SOUL.md`: naming a hand-off, a follow-up, a callback,
  or a team member to the customer **requires** a successful `toee_case` `create_case` in the
  same turn, with a `contact_reason`. Promising a human without opening a case is the defect,
  not merely a missed opportunity.
- Give the contact-reason vocabulary the model should use. `contact_reason` is free `TEXT` and
  the workbench edits it inline, so this is guidance, not a schema change — but an escalation
  raised without one now lands as `unspecified` (0.0.4), which reads as "someone escalated and
  did not say why".
- Add the should-escalate scenarios to the eval suite (the `case_created` assertion and its
  derivation already exist — `eval_runner/assertions.py:56`, `transcript.py:224`; 27 scenarios
  declare it, 23 expecting `true`). At minimum: an unmatched caller with an urgent billing
  dispute, and a question the agent cannot answer from knowledge.
- Report the escalation rate. `metrics.py` has no escalation counter today; the read can derive
  from `cases.contact_reason IS NOT NULL` per thread against auto-handled threads. Wire the
  panel row into **S22**'s existing strip rather than building a second surface.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** new should-escalate scenarios recorded and replaying green; each proven
  RED-capable (a recording without the `create_case` call flips it, then removed). Existing 27
  `case_created` scenarios still green.
- **② E2E:** drive the two conversations above through the simulator on a live stack and show
  a case with a non-null `contact_reason` on each thread — and, as the paired consequence, that
  neither thread now appears in the Auto-Handled Audit View.
- **③ Product (PAC):** owner replays the urgent-billing conversation and confirms it reaches
  the rep queue as a triaged case; feeds PAC-9.

## Out of scope

- **Making the replay gate live** — that is S31's subject and it must not become a gating
  change here (NFR-4, eval determinism).
- **The `should_have_escalated` → L6 proposal path** — already S25's, via the routing table.
  This slice must not add a second route for the same signal.
- **Over-escalation.** Tightening the contract can trade under-escalation for a case on every
  conversation, which would empty the Auto-Handled Audit View exactly as the pre-0.0.4 bug did.
  Name the rate in ② rather than only counting the misses.

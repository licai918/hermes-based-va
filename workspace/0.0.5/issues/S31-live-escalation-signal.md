# S31 — The launch gate cannot see escalation drift [EARLY BIRD]

- **Milestone:** 0.0.5 — complete the memory architecture
- **Track:** carry-in defect (found by the 0.0.4 quality-feedback acceptance run)
- **Size:** S
- **Depends on:** nothing. **Land this before S30** — it is the instrument that turns S30 from
  an anecdote into a measurement, and it has standalone value even if S30 slips.
- **Delivers:** no 0.0.5 FR — carry-in defect, see the README traceability note.
- **Surface:** CI (`Advisory live-model judge`), `eval_runner`, no production code

## The finding

The `case_created` assertion is not missing. It exists, it is derived correctly, and **27
scenarios declare it** — 23 expecting `true`, 4 expecting `false` (the "must NOT open a case"
side is covered too):

- `eval_runner/assertions.py:56` reads `result.case_created`
- `eval_runner/transcript.py:224` derives it from a successful `toee_case`/`create_case` call
- `eval/scenarios/06-refund-discount-refused.yaml` and 22 others carry
  `assertions.behavioral.case_created: true`

And it has fired in anger. An archived report still in the tree —
`eval/reports/text_first_launch-1781929935171.json` — records, **13 times**:

```
"name": "case_created",
"detail": "expected case_created=true, got false"
```

That is exactly the symptom S30 describes. **The harness has already caught this failure.**

## Why the gate is green anyway

The authoritative gate replays recordings. From `.github/workflows`:

```
--suite text_first_launch --harness replay --transcripts-dir ../eval/transcripts
--suite email_go_live    --harness replay --transcripts-dir ../eval/transcripts
```

`--harness replay` never queries the model. Every `case_created` assertion in the launch gate
re-checks a **transcript recorded at some past moment when the agent did escalate**. The gate
answers "does the recording still satisfy the assertion", which is a question about the file,
not about the agent. It passed in 15s on the acceptance PR while the live agent was failing
the same assertion twice out of two.

This is not a bug in the gate — determinism is deliberate and load-bearing (**NFR-4**,
0.0.5). It is a **coverage boundary that nothing currently states**, and the consequence is
that behavioural drift between a recording and the live model is structurally invisible to CI.
Any assertion in the replay suite has this property; `case_created` is simply the one that has
now been shown to drift.

## Approach

- **Do not make the replay gate live.** That would trade a deterministic wall for a flaky one
  and break NFR-4. The replay gate stays exactly as it is.
- Add a **live-model escalation check to the existing `Advisory live-model judge
  (non-blocking)` job** — the host already exists and is already non-gating, so this needs no
  new CI surface and cannot destabilise the required wall. A small should-escalate scenario set
  runs against the live model and reports `case_created` outcomes.
- **Report it where a human will see a trend, not just a build.** One red advisory run is
  noise; escalation rate falling over a fortnight is the signal. Emit to the same place S22's
  memory-health strip reads so drift shows up as a line, not an alert.
- **State the boundary in writing.** The replay suite's documentation (and any panel copy that
  quotes a green eval gate) must say that it verifies recordings, not current model behaviour.
  A green launch gate must never be read as "the agent still escalates" — the same class of
  overclaim S21/S23 already guard against for the safety leg, and worth saying once in the same
  words.

## Acceptance — three-layer gate (NFR-1)

- **① Technical:** the advisory job runs the should-escalate set against the live model and
  reports per-scenario `case_created`; proven RED-capable against a prompt variant with the
  hand-off contract removed; the required replay gate's runtime and determinism unchanged.
- **② E2E:** carve-out — CI/eval-instrumentation slice, ① only. The human-visible half is the
  trend row, which lands with S22.
- **③ Product (PAC):** feeds PAC-9 — the owner reads the escalation trend, not a build badge.

## Out of scope

- **Fixing the behaviour** — S30. This slice only makes the failure visible; it is deliberately
  useful before the fix exists, because it is what proves the fix worked.
- **Widening the gating assertion set** — explicitly a separate decision (same reasoning
  ADR-0160 already records for `_eval_safety`: widening what a gating assertion reads is its
  own slice, never a quiet extension).
- **Re-recording existing transcripts.** If a recording is found to be stale, say so in the
  report rather than re-recording it inside this slice — S23's scenario-17 warning applies.

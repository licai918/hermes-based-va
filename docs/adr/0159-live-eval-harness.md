# Live-eval harness: scripted gate + live-model advisory judge on every PR

> ADR number: **0159**. Free on both `main` (which tops out at ADR-0154) and
> `feat/0.0.4-land-all` (which tops out at ADR-0158) as of 2026-07-24 — no
> collision in either history. Recorded here because 0.0.4 has already paid for
> one same-day cross-branch number clash (see ADR-0155's renumbering note).

> **Status: Accepted — advisory judge wired, non-blocking** (decided during
> 0.0.4, S20; FR-28, FR-29, NFR-7). Ships on `feat/0.0.4-land-all`: the report
> renderer `hermes/eval_runner/judge_report.py`, the runnable
> `hermes-runtime/hermes_runtime/advisory_judge_report.py`, and the non-required
> `advisory-judge` job in `.github/workflows/ci.yml`. Builds on **S18** (the
> scripted/live turn harness, ADR-0121/ADR-0139) and **S27** (the tuned judge
> rubric/model, `eval_runner/judge_fixtures.py` + `judge_measure.py`, FR-29).

## Context

The eval story has two kinds of signal with opposite failure modes, and 0.0.4
needs both without letting one corrupt the other:

1. **Deterministic replay gate (required).** `python -m eval_runner --harness
   replay` replays recorded transcripts with no model, no network — byte-stable,
   never flakes. S19 made two suites required (`text_first_launch`,
   `email_go_live`); the `eval-gate` job is the authoritative go-live wall.
2. **LLM-judge semantic legs (advisory).** The "honored" / "no-unprompted-recall"
   legs need a real model to read the reply (`eval_runner/judge.py`). A live model
   is non-deterministic by nature, so it can never sit inside the required gate
   without making the wall flake — PRD §9 decision 4, pinned by
   `test_eval_advisory.py`'s gate-boundary sweep.

S27 measured that the cheap judge was weak on the ETA-vs-preference conflation
class and sharpened the rubric + made the model env-configurable
(`EVAL_JUDGE_MODEL`). What was missing (FR-28): that tuned judge never actually
ran on a PR. The judge existed and was measurable, but no PR saw its verdicts.

## Decision

### 1. Two harness modes, one seam — scripted for the gate, live for advisory

The S18 turn harness has one model boundary (`run_turn`). In **scripted mode**
(`EVAL_SCRIPTED_MODE=1`, `scripted_eval.py`) the completions are seeded from the
recorded transcript, so a real gateway/queue/turn-worker pipeline runs with **no
OpenRouter call** — this is what the required `harness-topology` and `eval-gate`
jobs use, and it is deterministic. In **live mode** the same seam is filled by
`hermes_runtime.openrouter.make_openrouter_run_turn` — a real model, gated on
`OPENROUTER_API_KEY`. The gate never runs live; advisory always may.

### 2. Every PR runs the tuned judge over the scenario set, as advisory

`advisory_judge_report.py` runs the S27-tuned judge (real OpenRouter model via
`resolve_judge_model` → `EVAL_JUDGE_MODEL` or the cheap default) over the labelled
scenario set (`JUDGE_FIXTURES`) and renders `judge_report.py`'s markdown —
verdicts (precision/recall/accuracy), the per-leg honored / no-unprompted-recall
breakdown, and every miss. The CI `advisory-judge` job attaches it as an artifact
**and** upserts one marker-keyed PR comment (re-runs edit it, they do not spam).

Scope note (honest): "the scenario set" here is the S27 **judge-precision** fixture
set — the ground-truthed replies that let the report show precision/recall, not
just bare verdicts. Running the *full live-reply topology* (real model generating
the replies, then judging them) on every PR is deliberately **not** built here: it
is the heavyweight, cost-and-flake-prone path, and it is a future enhancement, not
a gate. The judge-over-fixtures run is the every-PR real-model cadence that ships.

### 3. Advisory forever — promotion to a gate is a FUTURE ADR

This judge is advisory and **stays advisory**. It reports; it never blocks. Making
it a required check is explicitly deferred to a future ADR, and that ADR is
**contingent on measured judge precision** — the whole point of S27's
`judge_measure` harness is to produce the precision/recall number that would
justify promotion. Until a future slice can show the judge is precise enough that
a "miss" reliably means a real regression (not judge noise), gating on it would
convert judge flakiness into merge flakiness — exactly the failure PRD §9 decision
4 forbids. No promotion without that evidence.

Corollary (FR-29 — **no retry theater**): the advisory job reports what happened.
A "no"/undetermined verdict is the thing it exists to surface, not a failure to
retry away. It exits 0 on judge misses and flakes alike; flakes are data. The only
non-zero exit is a genuine "could not run at all" infra fault — and because the job
is non-required, even that blocks nothing.

### 4. Owner-key handling — graceful skip, self-arming

`OPENROUTER_API_KEY` is an owner-provided repo secret. The job passes
`${{ secrets.OPENROUTER_API_KEY }}` as env; the runnable's
`openrouter_configured()` check means an **absent** key writes the skipped report
and exits 0 — PRs are never blocked before the owner configures it, and the job
lights up with a real measurement the moment they add the secret, no code change.
The key is never printed, never committed (secret-scan stays green).

### 5. NFR-7 invariant — the required wall is unchanged

The `advisory-judge` job has **no `needs:`**, nothing needs it, and it is not in
any branch-protection required-status set. The required eval wall is exactly what
S19 left: the `eval-gate` scripted replay gate on `text_first_launch` +
`email_go_live`. This ADR adds a lane; it does not move the wall.

## Cost note

Every PR spends judge-model API calls: one completion per fixture in
`JUDGE_FIXTURES` (~13 today) on `EVAL_JUDGE_MODEL` (default cheap model). That is a
small, bounded, per-PR cost — an order of magnitude cheaper than a full
live-reply-generation run over every scenario, which is one reason the full
topology path is deferred (§2). If the fixture set or model cost grows, the first
levers are: sample the fixtures, or move the advisory run off per-PR onto a cadence
(the FR-31 honored-rate schedule already exists as a durable-queue job type, see
ADR-0155) — not a new gate.

## Consequences

- **The tuned judge is now visible on every PR** instead of being a measurable-
  but-unrun artifact. An owner reads one report end-to-end (PAC-8).
- **The advisory job needs `pull-requests: write`** — scoped to that one job, not
  the workflow default (which stays `contents: read`), so no other job's
  permissions widen.
- **Pure renderer, no product code.** `judge_report.py` lives in the dependency-
  free `eval_runner` package and is never imported by any deterministic-gate
  module, so `test_eval_advisory.py`'s "the gate never mentions judge" sweep still
  holds. The live client + key-skip live one layer out in `hermes_runtime`.
- **Branch protection is the owner's to set.** This ADR proves the job is
  non-required *in the workflow* (no `needs`, no required-set membership). The
  final "required checks" list is a GitHub repo setting the owner controls — the
  owner must NOT add `advisory-judge` to it (see the report's "needs the owner").

## Considered options

- **Judge inside the required gate (rejected).** Makes the required wall flake on
  every judge non-determinism — the exact thing PRD §9 decision 4 forbids.
- **Full live-reply topology on every PR (rejected for now).** Real model
  generating every reply, then judging — the faithful "live harness" but costly and
  flake-prone. Deferred to a future slice; the judge-over-fixtures run is the
  right-sized every-PR cadence today.
- **Fail the job on judge misses (rejected).** That is a gate wearing an advisory
  label. Advisory means exit 0 on misses; promotion is a separate, evidence-gated
  decision (§3).
- **Skip the job entirely until the owner adds a key (rejected).** A job that does
  not exist cannot self-arm. The graceful-skip path (§4) lets the wiring land now
  and light up the moment the secret appears, with the skip itself documented on
  the PR.

## Verification

- `hermes/tests/test_eval_judge_report.py` — the renderer over a mock/recorded
  judge response fed through `measure_judge`: marker + advisory banner + verdict
  summary, both legs broken out, misses table when the judge is wrong, the clean
  line when it is not, undetermined reported (not crashed), pipe-in-reason escaped,
  and the skipped report is clearly non-blocking. No key, no network.
- `hermes-runtime/tests/test_advisory_judge_report.py` — the runnable's two paths:
  key ABSENT → skipped report + exit 0; key PRESENT (injected fake judge) → full
  report; and exit 0 even when the judge returns garbage (FR-29). No live model.
- `judge_report.demo()` (`python -m eval_runner.judge_report`) — a runnable
  self-check that renders both paths from a mock-driven metrics object.
- The real-model path itself is owner-key-gated and cannot be exercised here; it is
  verified by construction (the same `measure_judge` code path the fake-client
  tests cover) and will produce its first real report when the owner adds the
  secret.

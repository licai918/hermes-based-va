# S08 — Implicit draft outcome write path (`record_draft_outcome`) — Report

Branch: `claude/qf-impl`
Parent: `6bf09a0` (S06 fix — submit_draft_rating requires + stores draft_text)

## Summary

Added `record_draft_outcome`, the IMPLICIT counterpart to S06's
`submit_draft_rating`: writes whether a rep sent a generated draft untouched
(`sent_as_is`) or edited it (`sent_edited` + a normalized edit-distance
ratio) into the SAME `draft_feedback` table (0019_draft_feedback.sql, no
migration needed — the table already carries every column this action
needs). No verdict, no reason tags on outcome rows (both stay NULL/empty) —
this mechanism records an outcome, not a judgment.

Reuses S06's fail-closed actor resolver (`resolve_draft_rating_authorization`)
and case-ownership gate (`_require_case_held_by`) verbatim, per the brief —
no third copy of either was written.

## Files changed

- `hermes/toee_hermes/drivers/mock/feedback.py` (extended):
  - `DRAFT_OUTCOMES = ("sent_as_is", "sent_edited")`
  - `_require_draft_outcome` — enum validator, mirrors `_require_draft_kind`.
  - `_read_edit_distance_ratio(params, *, outcome)` — required numeric when
    `outcome == "sent_edited"`, REJECTED (not silently dropped) when
    `outcome == "sent_as_is"` and a ratio is present anyway.
  - `record_draft_outcome` mock handler (was a stub returning
    `{"feedback_id": None, "status": "unavailable"}`) — now: resolve actor →
    validate `case_id`/`draft_correlation_id`/`draft_kind`/`outcome`/
    `draft_text` → validate ratio → append to the SAME `draft_ratings`
    in-memory list `submit_draft_rating` uses, so a rating and an outcome for
    one draft are two rows in one store, joinable by `draft_correlation_id`.
    No case-ownership check in the mock (same as `submit_draft_rating`: the
    mock has no case store to check against; enforced only in Postgres).

- `hermes-runtime/hermes_runtime/datastore/handlers/feedback.py` (extended):
  - Imports `_read_edit_distance_ratio`, `_require_draft_outcome` from the
    mock module (the "one resolver/validator, both twins" discipline).
  - `_record_draft_outcome(conn, params, context)`: actor gate first (same
    ordering as `_submit_draft_rating`) → field validation → case-ownership
    gate (`_require_case_held_by`, reused verbatim) → INSERT into
    `draft_feedback` (verdict/reason_tags left at their column defaults:
    NULL / `'{}'`) + `insert_audit` with a distinct action string
    `draft_outcome_recorded`, same transaction.
  - Registered in `feedback_handlers()` alongside `submit_interaction_review`
    and `submit_draft_rating`.

- `hermes/toee_hermes/plugin/schemas.py`: `record_draft_outcome`'s
  `PARAM_SCHEMAS` entry (added by an earlier slice, before the
  case-ownership gate was wired up) was missing `case_id` and `draft_text` —
  both now added as required properties, mirroring `submit_draft_rating`'s
  entry (which the S06 fix already made `draft_text`-required). `case_id` is
  required because the case-ownership gate needs it; `draft_text` is
  required for the same reason S06's fix made it required on
  `submit_draft_rating` — the generated-draft snapshot has no other place to
  live once it's sent.

No migration file added — 0019_draft_feedback.sql already declared every
column `record_draft_outcome` writes (`outcome`, `edit_distance_ratio`
nullable, `draft_text`), by design (S06's migration comment: "hence every
column below exists now even though this slice only populates a subset").

## Tests added

`hermes/tests/test_feedback.py` (mock-level, 12 new tests): happy path for
both outcomes, ratio required-on-`sent_edited`/rejected-on-`sent_as_is`,
unknown outcome, missing `draft_text`, no-actor policy_blocked, wrong-profile
policy_blocked, actor cannot be forged, and a correlation-join test
(`test_record_draft_outcome_and_submit_draft_rating_share_correlation_id`).

`hermes-runtime/tests/test_datastore_driver_feedback.py` (live-Postgres, 13
new tests): `sent_as_is` row persisted + read back, `sent_edited` row with a
plausible ratio (0.42) persisted + read back, audit row written with the
distinct action string, THE correlation-join test (a rating + an outcome for
the same `draft_correlation_id` are two distinct rows, `SELECT`ed back
together and asserted `rated_only`/`up` vs `sent_as_is`/`None`), no-actor →
policy_blocked + zero rows + zero audit rows, wrong-profile →
policy_blocked, case-ownership (unheld case, nonexistent case) →
policy_blocked + zero rows, ratio-required/ratio-rejected rejections persist
nothing, unknown outcome / missing draft_text persist nothing, actor cannot
be forged.

`hermes-runtime/tests/test_tool_dispatch_app.py` (dispatch-seam, 2 new
tests): `record_draft_outcome` dispatched with no actor → HTTP 200,
`ok: false`, `policy_blocked`, zero `draft_feedback` rows, zero
`draft_outcome_recorded` audit rows; dispatched by an attributed actor who
does not hold the case → `policy_blocked`, zero rows.

## Commands run + output

```
$ cd hermes-runtime && uv run pytest tests/test_datastore_driver_feedback.py tests/test_tool_dispatch_app.py -q
......................................................................   [100%]
70 passed in 7.57s
```

```
$ cd hermes && uv run pytest tests/test_feedback.py -q
..............................                                           [100%]
30 passed in 0.11s
```

Confirming DB tests actually ran (not skipped) — every new `record_draft_outcome`
test shows explicit PASSED, not SKIPPED:

```
$ cd hermes-runtime && uv run pytest tests/test_datastore_driver_feedback.py -v | grep -E "record_draft_outcome|correlation_id"
test_record_draft_outcome_sent_as_is_persists_a_row PASSED
test_record_draft_outcome_sent_edited_persists_a_plausible_ratio PASSED
test_record_draft_outcome_writes_an_audit_row PASSED
test_rating_and_outcome_for_the_same_draft_share_correlation_id_as_two_rows PASSED
test_record_draft_outcome_with_no_actor_persists_nothing PASSED
test_record_draft_outcome_is_policy_blocked_outside_internal_copilot PASSED
test_record_draft_outcome_on_a_case_the_actor_does_not_hold_persists_nothing PASSED
test_record_draft_outcome_on_a_nonexistent_case_persists_nothing PASSED
test_record_draft_outcome_sent_edited_without_ratio_persists_nothing PASSED
test_record_draft_outcome_sent_as_is_with_ratio_persists_nothing PASSED
test_record_draft_outcome_rejects_unknown_outcome_and_persists_nothing PASSED
test_record_draft_outcome_missing_draft_text_persists_nothing PASSED
test_record_draft_outcome_rep_cannot_be_forged PASSED
```

Broader regression suites (full repo, both packages):

```
$ cd hermes && uv run pytest -q
........................................................................ [100%]
708 passed in 1.85s
```

```
$ cd hermes-runtime && uv run pytest -q
........................................................................ [ 8%]
...(fastembed-skip lines only)...
843 passed, 3 skipped in 148.33s (0:02:28)
```

The 3 skips are pre-existing and unrelated to this slice — confirmed via
`-rs`:

```
SKIPPED [1] tests\test_knowledge_ingest.py:269: fastembed not installed
SKIPPED [1] tests\test_knowledge_retriever.py:251: fastembed not installed
SKIPPED [1] tests\test_knowledge_retriever.py:308: fastembed not installed
```

## Commit

- `<filled in after commit — see below>`

## Concerns (per instructions, noted rather than fixed here)

- **Validator/resolver duplication is now at two copies, by design, not
  three.** `resolve_draft_rating_authorization` and `_require_case_held_by`
  are reused verbatim by `record_draft_outcome` — no third copy was
  written, per the brief's explicit instruction. The remaining
  near-duplication is between S03's `resolve_interaction_review_authorization`
  (external mechanism) and S06/S08's `resolve_draft_rating_authorization`
  (internal mechanism) — two copies of the same fail-closed shape
  (`profile == internal_copilot` + `user_id` present), kept deliberately
  separate per S06's own docstring ("a future edit to one can't silently
  change the other's behavior"). A final-review consolidation pass could
  fold these into one parameterized gate; not attempted here as instructed.
- **`PARAM_SCHEMAS["record_draft_outcome"]` was already partially wired up
  by an earlier slice** (S02/S03 scaffolding) with `draft_correlation_id`,
  `draft_kind`, `outcome`, `edit_distance_ratio` but missing `case_id` and
  `draft_text`. This slice added the two missing required properties rather
  than rewriting the entry from scratch — worth a second look in review to
  confirm no caller relied on the old (looser) required-set.

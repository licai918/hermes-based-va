# Loop-closure metrics: the three denominators that do exist, and the ones that do not

> **Status: Accepted — implemented** (decided during 0.0.5, 2026-07-29). Ships on
> `feat/0.0.5-land-all`: S28 (FR-34b, US19, NFR-1/3/4/8, PRD Track T6). The other
> half of
> [ADR-0163](0163-memory-control-loop-lifecycle-metrics-and-read-only-knobs.md),
> which turned FR-34a's *rates* into *counts* because their denominators did not
> exist. This one is about the three places where a denominator **does** exist —
> and what has to be excluded from each before it means anything.

## Context

The control loop is now fully built: a reviewer scores a turn (S03/S06-0.0.4),
the aggregator clusters the failures and proposes (S25), edit-diff mining
proposes from what reps rewrite (S27), an admin confirms, the entry is injected
(S06/S09), and the judge scores the next turns (S22-0.0.4/S26). Every stage is
instrumented in isolation. **Nothing said whether the loop closes.**

FR-34b asks for the three numbers that would: feedback→proposal conversion,
post-fix re-fail, and the per-entry honored trend after a replacement. All three
are joins over rows the slices above already write — no new emit seam, no
migration. The work was never the SQL. It was deciding what each fraction is
over, because every one of them has a plausible denominator that is wrong.

## Decision

### 1. Conversion is over ROUTABLE signals, and the unroutable ones get their own number

The obvious denominator — every piece of failing feedback — is wrong, and D23
says why: of the eleven declared reason tags, the Signal Routing Table sends
**six** to a governed propose action and leaves **five** terminating outside the
memory layers. `policy_violation` and half of `factual_error` would need a
scheduled job to write slot *content*, which NFR-3 forbids;
`missed_information`/`missing_context` want a `review_item` kind D9's six-value
enum does not contain; `other` is a free-text escape hatch whose meaning lives in
the reviewer's comment.

A conversion rate over all feedback therefore counts *"the product has no
destination for this tag"* as a conversion failure, and drops as the mix of tags
shifts for reasons that have nothing to do with the loop.

**The denominator is routable signals only, and the unroutable share is a
first-class rate beside it** — `unroutable / all signals` — with the three
reasons named in its own detail. Folding them in would have hidden an owner
decision inside an engineering metric; leaving them out silently would have hidden
it entirely.

Two things are deliberately **inside** the denominator and unconverted: a signal
below the aggregator's N threshold, and one whose propose was refused by a write
scan (D13). Both reached nobody, which is the question the number asks. One thing
is deliberately outside the **numerator**: S27's edit-diff-mined proposals. An
edited send carries no reason tag, so it has no denominator here to belong to, and
counting it would inflate the rate with proposals the tag population never
contained.

Whether a tag is routable is **derived on every call** from
`FEEDBACK_SIGNAL_ROUTES` × `EMITTING_DESTINATIONS`, never written down. The
six/five split above is stated here as of today and pinned by a test that reads
the shipped table — because D23's own heading says the opposite ("six of eleven
have nowhere legal to emit") while its body lists five. A restated count is wrong
the moment a route moves; a derived one cannot be.

### 2. Post-fix re-fail: one watch window, doing two jobs

"The same tag recurring on the same subject after a confirmed fix" cannot be
implemented literally. A `draft_correlation_id` is minted per draft and never
repeats; an `auto_handled_record` is a *past* interaction, so re-reviewing it
after a fix re-judges pre-fix evidence rather than testing the fix. Matching on
subject alone would produce a structural zero — the same shape as D22's
`hit_count`, and a 0% re-fail rate is the most flattering lie this panel could
tell.

**A re-fail is: a failing feedback row created after the confirmation, carrying
the same reason tag, on a subject the confirmed proposal was NOT raised from.**
The subject exclusion is the whole comparability argument in one clause — the
original subjects are the evidence the fix was made from, so they cannot also be
the test of it.

**A fix is one confirmed feedback-derived L6 procedure proposal.** Persona-review
items are excluded even when acknowledged: acknowledging one changes nothing by
itself (the persona moves by dev edit + eval re-record), so counting it would put
a success rate on an intervention that never happened.

`POST_FIX_WATCH_WINDOW_SECONDS` does **two** jobs, and that is the point rather
than an economy:

1. a recurrence only counts inside that window after the confirmation, so every
   fix is judged over an equal-length observation period;
2. a fix only enters the denominator once that window has fully elapsed.

Without (2) a deployment that confirmed its first fix this morning reads a clean
0% — a fix nobody has had time to re-fail is not evidence that it held. The fixes
still maturing are reported in the tile's own detail, so the exclusion is visible
rather than indistinguishable from a small denominator.

**Stated ceiling:** a recurrence is dated by the feedback row's `created_at`, not
by when the interaction happened. A reviewer working through a backlog of pre-fix
interactions after a fix lands will read as a re-fail. The upgrade path is a
joinable timestamp on the reviewed subject, not a cleverer query.

### 3. The per-entry honored trend is split at each entry's own edit — and never reads `hit_count`

`entry_effectiveness` (S26) is a **full-recompute snapshot with no history**, so
an edited entry's current score mixes turns from before and after the edit into
one number. Reading it for a "trend" would compare the entry to itself, averaged.

So the trend is computed from the raw join instead: per entry, the judge's honored
leg over the turns `injection_ledger` says carried it, split at that entry's own
`updated_at`, using the console's existing "edited since decided" rule (D7 — an
edit is an in-place UPDATE, so the id, the usage and the ledger history all
survive it). An entry judged on only one side is excluded and counted, because a
before with no after is not a trend — and a retire-then-write replacement is a
new entry with no before at all.

**It must not lean on `hit_count`, and D22 is the reason**: `hit_count` counts
deterministic-seam applications, and the seam never applies a `default_rule`, so
every seasonal rule would report as dead however well it works. This is the same
correction D22 assigned to S20's retirement feed, applied one layer over.

### 4. No percentage below two observations — in the shared builder, not the renderer

A rate over one observation is 0% or 100% whichever way the truth points. On a
panel whose subject is *"does the loop work"*, those are the two most confident
wrong answers available, and this deployment is nearly all single-point cases: the
honored-rate job has never persisted an aggregate (no `OPENROUTER_API_KEY`), so
`judged_turn` is empty and the entry trend has no observations at all.

`MIN_OBSERVATIONS_FOR_RATE` lives in the **shared builder** both twins call, so
the rule cannot be implemented twice or forgotten by one renderer. Below it the
row still ships its numerator and denominator and the tile reads
"Not yet computed · 1 / 1": the *percentage* is withheld, never the evidence —
which is what separates "too little to say" from "nothing happened".

### 5. A rate travels with its population, and the BFF refuses one that does not

The wire type is `{key, label, detail, numerator, denominator, rate}` and the BFF
**refuses** a row missing `label`/`detail`/`numerator`/`denominator` rather than
rendering the bare number. This extends S14's Memory Hub rule and ADR-0163's
`{key, label, detail, value}` with the part a fraction adds: 25% over four fixes
and 25% over four hundred are not the same claim, and a reader must never be asked
to take the percentage on trust when the denominator *is* the argument.

## Consequences

- **Every one of the three rates reads "Not yet computed" on the shipped
  deployment**, and that is the correct answer, not a gap: no aggregator run has
  emitted, no feedback-derived proposal has been confirmed, and no turn has been
  judged. A zero-filled shape would have rendered a perfect re-fail rate for a
  loop that has never closed once.
- **Nothing gates (NFR-4).** These are read-only admin-panel aggregations off
  every turn path; only S21's adversarial safety leg may gate, and it still does.
- **Nothing is written (NFR-3).** No migration, no emit seam, no new counter —
  three joins over rows S09/S25/S26/S27 already write.
- **The conversion numerator depends on S25's audit-row shape**
  (`details->'emissions'`) and on its evidence key. Both are pinned against the
  shipped builders by tests rather than trusted, because a rename there would
  otherwise surface as "conversion quietly went to zero" rather than as a
  failure.
- **D23 is now a number on a page rather than a paragraph in a decision file.**
  If the owner funds a seventh `review_item` kind, this rate is where the
  improvement shows up; if they do not, it is where the cost stays visible.

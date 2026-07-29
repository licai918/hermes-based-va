"""FR-34's lifecycle counts and loop-closure rates, in ONE shape both metrics
twins build (0.0.5 S22 for FR-34a; S28 for FR-34b).

Conflict, pollution, privacy-deflection and the per-layer prompt drops are all
plain counts over rows earlier slices already write -- there is no new emit seam
here. What this module owns is the thing a count cannot be trusted without: its
SCOPE.

**A count travels with its scope as DATA, never as a naming convention.** S14
set the rule for the Memory Hub (``{label, value}`` on the wire, so no renderer
can drop the caveat) and S26 extended it (a score without ``scope`` and ``basis``
maps to null rather than to a bare number). Every row here carries ``label`` AND
``detail``: what is counted, over what window, and -- the half that is easiest to
lose -- **what is deliberately NOT in the number**. Two components of FR-34a's own
wording have no source in shipped code, and each says so at the count it belongs
to rather than being quietly summed as zero:

* *queue conflict annotations* -- S13's write-time advisories are not shipped.
* *poisoned retirements* -- no L6/L7 retirement records a poisoning reason, and
  S20's retirement feed is not shipped either.

**Every number here is a lifetime count, not a rate.** Nothing in the system
records "L4 writes attempted", so there is no denominator for a conflict or
pollution RATE, and inventing one out of the rows that happen to be countable
would be a percentage that looks like accuracy and is not -- the same correction
the honored-rate tile already carries. Counts are what is honestly countable.

The mock twin calls :func:`lifecycle_payload` with no arguments and the Postgres
twin calls it with its SQL counts, so the two cannot render different tiles
(NFR-7) -- the shared-BUILDER pattern ``deletion_success_payload`` established,
rather than a restatement pinned by an equality test.

**FR-34b (S28) adds RATES to the same file, and they are a different animal.**
:func:`loop_closure_payload` answers "did the loop close?", which is a question
about fractions: how much feedback became a proposal, how many confirmed fixes
came back, how many edited entries kept their honored score. Each row therefore
carries its ``numerator`` and ``denominator`` as data beside the ``rate``, so a
reader is never asked to trust a percentage whose population they cannot see --
and ``rate`` is withheld entirely below
:data:`MIN_OBSERVATIONS_FOR_RATE` observations, because 0% and 100% off a single
data point are the two most confident lies this panel could tell.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

# The three layers whose content is injected into a turn's prompt, and therefore
# the three that S19's per-layer read deadline can DROP from one. L1-L3 and L5
# are not rendered from this seam; see docs/architecture/memory-layers.md.
INJECTED_PROMPT_LAYERS: tuple[str, ...] = ("L4", "L6", "L7")

LIFECYCLE_CONFLICT = "conflict_overwrites"
LIFECYCLE_POLLUTION = "pollution_rejected_writes"
LIFECYCLE_SELF_SERVICE = "privacy_deflection_self_service"
LIFECYCLE_ERASURES = "privacy_deflection_erasures"
# One key per injected layer, e.g. ``prompt_layer_drops_L7``.
LIFECYCLE_DROP_KEY_PREFIX = "prompt_layer_drops_"


def _count(key: str, label: str, detail: str, value: Optional[int]) -> dict[str, Any]:
    return {"key": key, "label": label, "detail": detail, "value": value}


def lifecycle_payload(
    *,
    conflict_overwrites: int = 0,
    pollution_rejected: int = 0,
    self_service_clears: int = 0,
    binding_erasures: int = 0,
    layer_drops: Optional[Mapping[str, int]] = None,
) -> dict[str, Any]:
    """FR-34a's counts, each beside the exact thing it counts.

    ``layer_drops`` is keyed by the layer names in
    :data:`INJECTED_PROMPT_LAYERS`; a missing layer reads 0, which is the true
    answer for a layer no turn has ever dropped.
    """
    drops = dict(layer_drops or {})
    return {
        "lifecycle": [
            _count(
                LIFECYCLE_CONFLICT,
                "Conflicting L4 overwrites",
                "Preference writes that replaced an existing slot value with a "
                "DIFFERENT one (S07's `preference_updated` audit rows, the same "
                "`is_differing_value_overwrite` rule the write path uses). A "
                "lifetime total over the whole audit log, not a window, and not a "
                "rate: nothing records how many writes were attempted, so there is "
                "no denominator to divide by. FR-34a also names queue conflict "
                "annotations; S13's write-time advisories are not shipped, so "
                "nothing of theirs is in this number.",
                conflict_overwrites,
            ),
            _count(
                LIFECYCLE_POLLUTION,
                "L4 writes rejected by the injection scan",
                "Customer-memory writes hard-rejected at the write seam because "
                "the value or its evidence matched an injection pattern (S08, "
                "FR-10). One row per rejection, committed even though the write "
                "rolled back, so a rejection always leaves a trace. Lifetime "
                "total, not a rate. FR-34a also names poisoned retirements; no "
                "L6/L7 retirement records a poisoning reason today, so none is "
                "counted here.",
                pollution_rejected,
            ),
            _count(
                LIFECYCLE_SELF_SERVICE,
                "Customer self-service clears (privacy-deflection PROXY)",
                "PROXY, and labelled as one (owner decision ⑤): a verified "
                "customer clearing one of their own preference slots. It is what "
                "the system can see, and it is NOT the privacy-complaint rate -- "
                "a customer who complains through a phone call or a review leaves "
                "no row anywhere in this system. The same counter the "
                "Self-service usage tile shows, repeated here because it is the "
                "only shipped component of this metric.",
                self_service_clears,
            ),
            _count(
                LIFECYCLE_ERASURES,
                "Whole-binding erasures (forget-me)",
                "Administrator-run erases of a customer's entire memory binding "
                "and every linked channel's provisional binding (S11, FR-13). "
                "Counted from the summary audit row, one per binding touched, so "
                "one customer's erase across three linked channels counts three. "
                "Whether the data STAYED erased is the separate deletion-success "
                "tile, not this count.",
                binding_erasures,
            ),
            *(
                _count(
                    f"{LIFECYCLE_DROP_KEY_PREFIX}{layer}",
                    f"{layer} dropped from a prompt (deadline)",
                    "Turns where the S19 pre-turn read deadline expired and this "
                    "layer contributed nothing to the prompt -- fail-open, so the "
                    "reply still went out without it. The budget ships OFF "
                    "(MEMORY_READ_BUDGET on the knob panel), so on a deployment "
                    "that has not switched it on this is structurally 0 and a "
                    "non-zero would mean the switch is on. A dropped layer is "
                    "silent context loss, which is why it is counted rather than "
                    "only logged.",
                    int(drops.get(layer, 0)),
                )
                for layer in INJECTED_PROMPT_LAYERS
            ),
        ]
    }


# --- FR-34b (0.0.5 S28): proving the loop CLOSES ------------------------------

# The smallest denominator a percentage is reported over. A rate over ONE
# observation is 0% or 100% whichever way the truth points, so it carries no
# information and reads as certainty -- "a trend with one data point is not a
# trend", made mechanical rather than left to the reader's judgement. Below the
# floor the row still ships its raw numerator and denominator, so the tile reads
# "Not yet computed - 1 / 1" and the evidence is visible; it is the PERCENTAGE
# that is withheld, never the counts.
MIN_OBSERVATIONS_FOR_RATE = 2

LOOP_CONVERSION = "feedback_proposal_conversion"
LOOP_UNROUTABLE = "unroutable_feedback_signals"
LOOP_REFAIL = "post_fix_refail"
LOOP_ENTRY_TREND = "entry_honored_after_edit"


def _rate_row(
    key: str, label: str, detail: str, numerator: int, denominator: int
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "detail": detail,
        "numerator": int(numerator),
        "denominator": int(denominator),
        "rate": (
            round(numerator / denominator, 4)
            if denominator >= MIN_OBSERVATIONS_FOR_RATE
            else None
        ),
    }


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def loop_closure_payload(
    *,
    converted_signals: int = 0,
    routable_signals: int = 0,
    unroutable_signals: int = 0,
    total_signals: int = 0,
    refailed_fixes: int = 0,
    matured_fixes: int = 0,
    maturing_fixes: int = 0,
    improved_entries: int = 0,
    compared_entries: int = 0,
    one_sided_entries: int = 0,
) -> dict[str, Any]:
    """FR-34b's three loop-closure rates, each beside the population it is over.

    Called with no arguments by the mock twin and with its SQL counts by the
    Postgres twin, exactly like :func:`lifecycle_payload` -- so neither twin can
    render a tile the other lacks, and every caveat below has one home.

    ``maturing_fixes`` and ``one_sided_entries`` are the observations each rate
    deliberately EXCLUDES. They are interpolated into the detail rather than
    dropped, because an exclusion nobody can see is indistinguishable from a
    denominator that was simply small.
    """
    return {
        "loop_closure": [
            _rate_row(
                LOOP_CONVERSION,
                "Feedback that became a proposal (routable signals)",
                "NUMERATOR: (reason tag x feedback row) pairs the feedback "
                "aggregator names as the evidence behind a proposal it actually "
                "raised, read back from its own run audit rows -- so a proposal "
                "that never cited a signal is not counted as converting one. "
                "DENOMINATOR: failing feedback rows x their reason tags over the "
                "same span, restricted to the tags the Signal Routing Table sends "
                "to a governed propose action. WINDOW: the aggregator's own "
                "clustering window (CLUSTER_WINDOW_SECONDS on the knob panel), "
                "because that is the only span the job ever looked at -- a wider "
                "denominator would count feedback it was never offered. NOT in "
                "the denominator: signals whose tag has nowhere legal to emit "
                "(the next row) -- folding those in would score a missing product "
                "destination as a conversion failure. IN the denominator and "
                "unconverted on purpose: a signal below the aggregator's N "
                "threshold (SAME_TAG_FAIL_THRESHOLD), and one a write scan "
                "refused -- both reached nobody, which is the question this "
                "number asks. NOT in the numerator: proposals mined from "
                "edit-diffs (FR-33); an edited send carries no reason tag, so it "
                "has no denominator here to belong to.",
                converted_signals,
                routable_signals,
            ),
            _rate_row(
                LOOP_UNROUTABLE,
                "Feedback with nowhere legal to go (D23)",
                "Failing feedback whose reason tag terminates OUTSIDE the memory "
                "layers, over ALL failing feedback in the same window. This is an "
                "owner decision recorded as a number, not a defect in the "
                "aggregator: the policy tag has no propose-shaped KnowledgeOps "
                "action, and a scheduled job writing slot CONTENT is the "
                "auto-write NFR-3 forbids; the information-gap tags want a "
                "review_item kind that D9's six-value enum does not contain; the "
                "factual tag's lexicon half needs a surface->canonical PAIR that "
                "a tag cluster does not carry; and `other` is a free-text escape "
                "hatch whose meaning lives in the reviewer's comment, so the tag "
                "alone says nothing to propose. A reviewer who picks one of these "
                "gets a counted-but-silent outcome -- this is how loud that is. A "
                "tag with no routing-table entry at all lands here too: "
                "routability fails closed.",
                unroutable_signals,
                total_signals,
            ),
            _rate_row(
                LOOP_REFAIL,
                "Confirmed fixes that came back",
                "NUMERATOR: matured fixes that re-failed at least once -- two "
                "recurrences against one fix count ONE, because the question is "
                "whether that fix held, not how loudly it did not. DENOMINATOR: "
                "MATURED fixes only. A fix is a feedback-derived L6 procedure "
                "proposal an administrator CONFIRMED; it matures once "
                "POST_FIX_WATCH_WINDOW_SECONDS (knob panel) has fully elapsed "
                "since that confirmation. A re-fail is a failing feedback row "
                "CREATED inside that same window afterwards, carrying the SAME "
                "reason tag, on a subject the confirmed proposal was not raised "
                "from. What makes the two sides comparable: every matured fix is "
                "watched for exactly the same length of time, and the original "
                "subjects are excluded because re-reviewing a pre-fix interaction "
                "re-judges the old evidence rather than testing the fix. "
                f"EXCLUDED: {_plural(maturing_fixes, 'confirmed fix', 'confirmed fixes')} "
                "still inside the watch window -- counting a fix nobody has had "
                "time to re-fail as clean is how a fresh deployment reads 0%. "
                "Also excluded: acknowledged persona-review items, which change "
                "nothing on their own (the persona moves by dev edit + eval "
                "re-record), and rejected proposals, which decided no fix. "
                "CEILING: a recurrence is dated by the feedback row's created_at, "
                "not by when the interaction happened, so a reviewer working "
                "through a backlog of pre-fix interactions reads as a re-fail.",
                refailed_fixes,
                matured_fixes,
            ),
            _rate_row(
                LOOP_ENTRY_TREND,
                "Edited L7 entries that held or improved their honored rate",
                "NUMERATOR: edited entries whose honored rate AFTER the edit is at "
                "least what it was before. DENOMINATOR: edited entries with "
                "determinate honored verdicts on BOTH sides of their own edit. "
                "\"Edited\" is the console's own rule -- updated_at later than the "
                "decision (D7: an edit is an in-place UPDATE, so the entry id, its "
                "usage and its ledger history all survive it). The split is per "
                "entry, over the turns the injection ledger says carried that "
                "entry, scored by the judge's honored leg. It reads the ledger x "
                "verdict join and NEVER hit_count: hit_count is structurally zero "
                "for every default_rule (D22), so a hit-based version of this "
                "number would report a healthy seasonal rule as dead. "
                f"EXCLUDED: {_plural(one_sided_entries, 'edited entry', 'edited entries')} "
                "judged on only one side of the edit -- a before with no after is "
                "not a trend, and a retire-then-write replacement is a new entry "
                "with no before at all. External customer turns only (D4.3): a "
                "copilot draft turn's id is synthetic, so its injections are "
                "recorded and never attributed. How far \"before\" can reach is "
                "bounded by the ledger's retention (PRUNE_WINDOW_SECONDS).",
                improved_entries,
                compared_entries,
            ),
        ]
    }

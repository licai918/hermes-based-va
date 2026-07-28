"""FR-34a's lifecycle counts, in ONE shape both metrics twins build (0.0.5 S22).

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

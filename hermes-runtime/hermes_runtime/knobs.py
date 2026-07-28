"""The READ-ONLY knob panel (0.0.5 S22, FR-34a; D14, D16).

Every number that tunes the memory control loop, rendered beside the module it
lives in and the env var (if any) that overrides it.

**Read-only, and that is a decision, not a shortcut (D14).** A panel that renders
env-var names is not an audited config change path, so 0.0.5 records plainly that
NFR-3's knob clause is satisfied by DEPLOY-TIME CONFIG ONLY: a knob moves by a
code/config commit whose audit trail is git history, and there is no in-app
mutation. Building a toggle that looked mutable and was not would satisfy the
letter of the goal and lie to the admin. The owner may fund a real governed
config action + audit row + config table later; until then this panel displays
and never writes.

**It READS the shipped constants; it never re-types their values (D16).** Every
row below is an import. A literal beside a constant would be a second source of
truth that agrees on the day it is written and drifts silently afterwards --
which is precisely the failure that made D16 a decision rather than a
preference. ``tests/test_lifecycle_metrics.py`` asserts both halves: each value
equals its constant, and the module source contains no copy of one.

**Why the mock twin reports nothing instead of this list.** These constants are
``hermes_runtime``'s, and ``toee_hermes`` must not import back (the package
dependency runs one way). The mock retention twin already answers that question
the same way -- it reports a NULL ledger-prune window rather than a copied number
-- and an absent panel is the honest form of "this backend does not run these
knobs", where a copied list would be wrong the day one of them is tuned.

The imports are function-local. This runs on the admin read path only, once per
panel load, and ``feedback_aggregator`` in particular drags the job machinery
into the import graph of every module that touches the datastore handlers
otherwise -- the same reason ``latency._budget_ms`` imports the knowledge
driver lazily.
"""

from __future__ import annotations

from typing import Any, Optional

PANEL_LABEL = (
    "Read-only. These knobs move by deploy-time config commit, never from this "
    "page: their audit trail is git history (D14 — NFR-3's knob clause is "
    "satisfied by config commits, with no in-app enforcement this iteration)."
)


def _knob(
    key: str,
    label: str,
    value: Any,
    source: str,
    note: str,
    env: Optional[str] = None,
) -> dict[str, Any]:
    """One row. ``value`` is stringified here so no renderer formats it twice."""
    return {
        "key": key,
        "label": label,
        "value": str(value),
        "source": source,
        "env": env,
        "note": note,
    }


def knob_panel() -> dict[str, Any]:
    """The panel's payload: the block's own read-only statement plus every knob."""
    from toee_hermes.drivers.mock.memory import ERASE_REAPPEARANCE_WINDOW_DAYS
    from toee_hermes.drivers.mock.retention import (
        PROVISIONAL_RETENTION_DAYS,
        VERIFIED_RETENTION_DAYS,
    )
    from toee_hermes.drivers.mock.semantic_lexicon import (
        HEALTH_USAGE_SATURATION,
        HEALTH_WEIGHT_HONORED,
        HEALTH_WEIGHT_MISAPPLIED,
        HEALTH_WEIGHT_STALE,
        HEALTH_WEIGHT_USAGE,
    )

    from .feedback_aggregator import (
        CLUSTER_WINDOW_SECONDS,
        SAME_TAG_FAIL_THRESHOLD,
        SIMILAR_EDIT_DIFF_THRESHOLD,
    )
    from .injection_ledger import PRUNE_WINDOW_SECONDS, ZERO_HIT_WINDOW_SECONDS
    from .latency import (
        MEMORY_READ_BUDGET_ENV,
        MEMORY_READ_DEADLINE_MS,
        PRE_TURN_READ_SLO_P95_MS,
        memory_read_budget_enabled,
    )
    from .tool_backend import (
        LEXICON_GLOSSARY_LIMIT,
        LEXICON_SELECTION_ENV,
        lexicon_selection_strategy,
    )

    return {
        "label": PANEL_LABEL,
        "knobs": [
            _knob(
                "LEXICON_GLOSSARY_LIMIT",
                "L7 prompt glossary window",
                LEXICON_GLOSSARY_LIMIT,
                "hermes_runtime.tool_backend",
                "How many confirmed lexicon entries the prompt's glossary may "
                "carry. Past this, a confirmed entry stops being rendered and the "
                "agent simply stops using it — silently. Raising it widens the "
                "prompt; the entries that fill it are the next knob.",
            ),
            _knob(
                "LEXICON_SELECTION",
                "L7 glossary selection strategy (effective)",
                lexicon_selection_strategy(),
                "hermes_runtime.tool_backend",
                "WHICH confirmed entries fill that window: `newest` (default) or "
                "`health` (round-robin by entry kind over the effectiveness "
                "score, so a seasonal default_rule cannot be starved out by hot "
                "aliases). FAIL-SAFE by design: any unrecognised value — a typo "
                "included — resolves to the shipped `newest` behaviour rather "
                "than to an empty glossary.",
                env=LEXICON_SELECTION_ENV,
            ),
            _knob(
                "PRUNE_WINDOW_SECONDS",
                "Injection-ledger retention",
                PRUNE_WINDOW_SECONDS,
                "hermes_runtime.injection_ledger",
                "How long a per-turn injection record is kept. It bounds every "
                "windowed usage read: blast radius, per-entry effectiveness, and "
                "the zero-hit window below. Must stay >= the zero-hit window, or "
                "garbage collection manufactures retirement candidates for "
                "entries that are actively in use (D12, asserted by a test).",
            ),
            _knob(
                "ZERO_HIT_WINDOW_SECONDS",
                "Zero-hit retirement window",
                ZERO_HIT_WINDOW_SECONDS,
                "hermes_runtime.injection_ledger",
                "How far back usage is looked for before an entry counts as "
                "unused. Deliberately shorter than the ledger's retention above.",
            ),
            _knob(
                "ERASE_REAPPEARANCE_WINDOW_DAYS",
                "Erase re-appearance watch window",
                ERASE_REAPPEARANCE_WINDOW_DAYS,
                "toee_hermes.drivers.mock.memory",
                "How long after a whole-binding erase the FR-14 tripwire keeps "
                "watching that binding. A slot found on it inside this window is "
                "flagged for a human — never re-deleted automatically.",
            ),
            _knob(
                "VERIFIED_RETENTION_DAYS",
                "L4 retention — verified bindings",
                VERIFIED_RETENTION_DAYS,
                "toee_hermes.drivers.mock.retention",
                "How long a verified customer's untouched preference slot "
                "survives the retention sweep.",
            ),
            _knob(
                "PROVISIONAL_RETENTION_DAYS",
                "L4 retention — provisional bindings",
                PROVISIONAL_RETENTION_DAYS,
                "toee_hermes.drivers.mock.retention",
                "The same for an unmerged provisional binding — shorter, because "
                "an orphaned provisional key belongs to nobody the system can "
                "name.",
            ),
            _knob(
                "SAME_TAG_FAIL_THRESHOLD",
                "Feedback aggregator — N (same-tag failures)",
                SAME_TAG_FAIL_THRESHOLD,
                "hermes_runtime.feedback_aggregator",
                "How many failures carrying the same tag on the same subject "
                "must cluster before the aggregator proposes anything. Lower it "
                "and the review queue fills with noise; raise it and real "
                "patterns take longer to surface.",
            ),
            _knob(
                "SIMILAR_EDIT_DIFF_THRESHOLD",
                "Feedback aggregator — M (similar edits)",
                SIMILAR_EDIT_DIFF_THRESHOLD,
                "hermes_runtime.feedback_aggregator",
                "The same bar for the edited-draft signal.",
            ),
            _knob(
                "CLUSTER_WINDOW_SECONDS",
                "Feedback aggregator — clustering window",
                CLUSTER_WINDOW_SECONDS,
                "hermes_runtime.feedback_aggregator",
                "How far back signals are gathered before clustering. Signals "
                "older than this never join a cluster.",
            ),
            _knob(
                "PRE_TURN_READ_SLO_P95_MS",
                "Pre-turn read SLO (p95)",
                PRE_TURN_READ_SLO_P95_MS,
                "hermes_runtime.latency",
                "The owner's line for the L4+L6+L7 read total. It is the budget "
                "the SLO tile is judged against; it enforces nothing on its own.",
            ),
            _knob(
                "MEMORY_READ_DEADLINE_MS",
                "Per-layer read deadline",
                MEMORY_READ_DEADLINE_MS,
                "hermes_runtime.latency",
                "How long ONE pre-turn layer read may take before it is dropped "
                "from the prompt, fail-open. DERIVED from the connect budget "
                "rather than set here — a read cannot sensibly be given less "
                "time than opening its own connection takes. Only in force when "
                "the switch below is on.",
            ),
            _knob(
                "MEMORY_READ_BUDGET",
                "Per-layer read deadline — enabled",
                memory_read_budget_enabled(),
                "hermes_runtime.latency",
                "The switch for the deadline above. Ships OFF against evidence: "
                "the measured pre-turn read total is far inside the SLO, and "
                "FR-27 says to optimize only what the histogram indicts. Turning "
                "it on makes the layer-drop counts on the lifecycle panel "
                "reachable.",
                env=MEMORY_READ_BUDGET_ENV,
            ),
            _knob(
                "HEALTH_USAGE_SATURATION",
                "Entry health — usage saturation",
                HEALTH_USAGE_SATURATION,
                "toee_hermes.drivers.mock.semantic_lexicon",
                "Where usage stops earning score. Without a ceiling the one hot "
                "normalizer would outrank everything else for ever.",
            ),
            _knob(
                "HEALTH_WEIGHT_USAGE",
                "Entry health — usage weight",
                HEALTH_WEIGHT_USAGE,
                "toee_hermes.drivers.mock.semantic_lexicon",
                "Weight of saturated usage in the effectiveness score.",
            ),
            _knob(
                "HEALTH_WEIGHT_HONORED",
                "Entry health — honored weight",
                HEALTH_WEIGHT_HONORED,
                "toee_hermes.drivers.mock.semantic_lexicon",
                "Weight of the honored judge leg. An entry nobody has judged "
                "scores neutrally on this leg, never zero — scoring it badly "
                "would be a ratchet it could not climb back out of.",
            ),
            _knob(
                "HEALTH_WEIGHT_MISAPPLIED",
                "Entry health — misapplication penalty",
                HEALTH_WEIGHT_MISAPPLIED,
                "toee_hermes.drivers.mock.semantic_lexicon",
                "How hard a failed no-misapplication verdict counts against an "
                "entry.",
            ),
            _knob(
                "HEALTH_WEIGHT_STALE",
                "Entry health — stale-use penalty",
                HEALTH_WEIGHT_STALE,
                "toee_hermes.drivers.mock.semantic_lexicon",
                "The same for stale use. `no_stale_use` is calibrated but NOT in "
                "the production judge set, so this weight has nothing to apply "
                "today and the leg's rate reads as null rather than as a "
                "flattering pass rate.",
            ),
        ],
    }

"""Per-entry effectiveness: judge verdicts x the injection ledger (0.0.5 S26, FR-31).

The DB half of migration ``0028_entry_effectiveness``. The scoring FORMULA and the
health-ranked selection are pure and live in
:mod:`toee_hermes.drivers.mock.semantic_lexicon` -- the ONE shared L7 resolver
both twins already import (NFR-7) -- and are re-exported here so a caller reaching
for effectiveness finds all of it in one place.

**What this joins, and what it deliberately does not.**
``injection_ledger`` (S09) says which entries reached which turn; ``judged_turn``
says how the judge scored that turn, per leg, keyed by the SAME ``turn_ref``.
Joining them gives per-entry honored / misapplied / stale. Usage comes from two
already-materialized places and is never recomputed here: the ledger's own row
count (windowed by its 180-day retention) and ``semantic_lexicon.hit_count``, the
column S05's scheduled rollup maintains (D6).

**EXTERNAL PATH ONLY (D4.3).** ``judged_turn`` rows can only ever come from the
scheduled judge job, which samples ``message_turn`` joined to
``agent_turn_context`` -- the external customer turn. The copilot draft path's
``turn_ref`` is a synthetic ``new_id("copilot_turn")`` with no durable identity, so
its ledger rows exist, are never judged, and are never attributed. That scope
ships as DATA on every score (``entry_health["scope"]``), not only in this
docstring, so no renderer can present a partial number as a total one.

**The refresh is a full recompute, not an accumulation** -- see the migration for
why (an overlapping sampling window would otherwise count one turn's evidence once
per run).

**Nothing here writes or retires memory content (NFR-3).** The score is a read-side
signal: it orders which CONFIRMED entries fill the prompt's bounded window, and it
decorates the admin console. It never changes an entry's status, its text, or its
existence. S20's retirement feed is not landed yet; when it is, the score it should
carry is :func:`health_for_rows` over :func:`entry_effectiveness_for` -- the same
two calls the console read makes, layer-generic already -- and it must still
PROPOSE a retirement for a human to decide.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Mapping, Optional

from toee_hermes.drivers.mock.semantic_lexicon import (  # noqa: F401  (re-export)
    EXTERNAL_PATH_SCOPE,
    HEALTH_HONORED_LEG,
    HEALTH_MISAPPLIED_LEG,
    HEALTH_STALE_LEG,
    HEALTH_USAGE_SATURATION,
    HEALTH_WEIGHT_HONORED,
    HEALTH_WEIGHT_MISAPPLIED,
    HEALTH_WEIGHT_STALE,
    HEALTH_WEIGHT_USAGE,
    lexicon_entry_health,
    select_ranked_entries,
)

logger = logging.getLogger(__name__)


def record_judged_turns(
    cur, verdicts: Iterable[tuple[str, str, Optional[bool]]]
) -> None:
    """Persist ``(turn_ref, leg, passed)`` verdicts on a CALLER-OWNED cursor.

    ``passed=None`` is the judge's own "undetermined" -- stored as SQL NULL,
    counted, and never in a denominator.

    ``ON CONFLICT DO UPDATE`` rather than ``DO NOTHING``: the sampling window
    overlaps run to run, so the same turn is re-judged routinely and the LATEST
    verdict is the one that should stand. Double counting is not a risk here
    because the aggregate is a full recompute, not an accumulation.
    """
    rows = [(turn_ref, leg, passed) for turn_ref, leg, passed in verdicts if turn_ref]
    if not rows:
        return
    cur.executemany(
        """
        INSERT INTO judged_turn (turn_ref, leg, passed)
        VALUES (%s, %s, %s)
        ON CONFLICT (turn_ref, leg) DO UPDATE
        SET passed = EXCLUDED.passed, judged_at = now()
        """,
        rows,
    )


def refresh_entry_effectiveness(conn) -> int:
    """Recompute ``entry_effectiveness`` from the ledger x verdicts join.

    DELETE + INSERT in ONE transaction on a CALLER-OWNED connection (no commit):
    readers keep seeing the previous snapshot until the caller commits, and an
    entry whose ledger rows have aged out of the retention window disappears
    instead of lingering as a ghost row with a stale score.

    The join is an INNER join on ``turn_ref``. A judged turn that carried no
    injection (the sampler's non-injection floor) contributes to no entry, and a
    ledger entry whose turn was never judged still gets its ``injections`` count
    with an empty ``leg_results`` -- usage without a verdict, stated as such.

    Returns the number of ``(layer, entry_ref)`` rows written.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM entry_effectiveness")
        cur.execute(
            """
            WITH per_leg AS (
                SELECT il.layer, il.entry_ref, jt.leg,
                       count(*) FILTER (WHERE jt.passed IS TRUE)     AS passed,
                       count(*) FILTER (WHERE jt.passed IS NOT NULL) AS determinate,
                       count(*) FILTER (WHERE jt.passed IS NULL)     AS undetermined
                  FROM injection_ledger il
                  JOIN judged_turn jt ON jt.turn_ref = il.turn_ref
                 GROUP BY il.layer, il.entry_ref, jt.leg
            ), usage AS (
                SELECT layer, entry_ref, count(*) AS injections
                  FROM injection_ledger
                 GROUP BY layer, entry_ref
            )
            INSERT INTO entry_effectiveness
                (layer, entry_ref, injections, leg_results, computed_at)
            SELECT u.layer, u.entry_ref, u.injections,
                   coalesce(
                       (SELECT jsonb_object_agg(
                                   p.leg,
                                   jsonb_build_object(
                                       'passed', p.passed,
                                       'determinate', p.determinate,
                                       'undetermined', p.undetermined))
                          FROM per_leg p
                         WHERE p.layer = u.layer AND p.entry_ref = u.entry_ref),
                       '{}'::jsonb),
                   now()
              FROM usage u
            """
        )
        written = cur.rowcount
    logger.info("entry_effectiveness recomputed: %s entry row(s)", written)
    return written


def entry_effectiveness_for(
    cur, *, layer: str, entry_refs: Optional[Iterable[str]] = None
) -> dict[str, dict[str, Any]]:
    """``{entry_ref: {"injections": n, "leg_results": {...}}}`` for ONE layer.

    A missing key means "nothing recorded" -- never a zero rate. Scoped by layer
    because ``entry_ref`` is only unique within one (L4 refs are
    ``binding_key:slot_name``, L6/L7 refs are entry ids).

    Wants a cursor with the DEFAULT (tuple) row factory: it unpacks positionally,
    so a ``dict_row`` cursor borrowed from a neighbouring query yields dictionaries
    and fails on the first row.
    """
    refs = None if entry_refs is None else list(entry_refs)
    if refs is not None and not refs:
        return {}
    cur.execute(
        """
        SELECT entry_ref, injections, leg_results
          FROM entry_effectiveness
         WHERE layer = %s AND (%s::text[] IS NULL OR entry_ref = ANY(%s))
        """,
        (layer, refs, refs),
    )
    out: dict[str, dict[str, Any]] = {}
    for entry_ref, injections, leg_results in cur.fetchall():
        if isinstance(leg_results, (str, bytes)):
            leg_results = json.loads(leg_results)
        out[entry_ref] = {
            "injections": int(injections or 0),
            "leg_results": leg_results if isinstance(leg_results, dict) else {},
        }
    return out


def health_for_rows(
    rows: list[dict[str, Any]], effectiveness: Mapping[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach ``entry_health`` to lexicon rows from an effectiveness lookup.

    ONE place where ``hit_count`` (materialized, D6) meets the ledger-derived
    numbers, shared by the admin console read and the health-ranked glossary
    selection -- so the number an admin sees and the number that decides what
    reaches the prompt can never be two different formulas.
    """
    for row in rows:
        found = effectiveness.get(str(row.get("id") or ""), {})
        row["entry_health"] = lexicon_entry_health(
            hits=row.get("hit_count") or 0,
            injections=found.get("injections") or 0,
            leg_results=found.get("leg_results") or {},
        )
    return rows

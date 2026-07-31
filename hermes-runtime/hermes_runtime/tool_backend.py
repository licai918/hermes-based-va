"""Tool-driver backend selection for the deterministic dispatch surface.

The per-profile ``tools:dispatch`` app (ADR-0141) runs the same governed
:func:`toee_hermes.execute.execute_tool` the channel pipeline uses; this module
picks which :class:`~toee_hermes.execute.ToolDriver` backs it. Mock-first
(ADR-0137): unset or ``mock`` selects the in-memory MockDriver; ``datastore``
selects the Postgres system-of-record driver (ADR-0140).

This is a **separate axis** from ``INTEGRATION_DRIVER`` (the external-vendor
backend, ADR-0137): ``TOOL_BACKEND`` chooses the system-of-record store for the
internal ``toee_*`` tools, while ``INTEGRATION_DRIVER`` chooses the external
integration backend (mock | composio). The PostgresDriver lives in this
embedding venv because ``psycopg`` must never reach the dependency-free
``toee_hermes`` plugin (ADR-0096/0100); importing it is deferred to the datastore
branch so a mock-first app never imports the database adapter.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from toee_hermes.drivers.mock import MockDriver, create_all_mock_handlers
from toee_hermes.execute import ToolDriver

from .metrics import MEMORY_INJECTION, emit_metric_event

logger = logging.getLogger(__name__)

# Env var selecting the dispatch backend. Values: "mock" | "datastore".
TOOL_BACKEND_ENV = "TOOL_BACKEND"
KNOWN_BACKENDS: tuple[str, ...] = ("mock", "datastore")

_UNSET = object()


def resolve_tool_backend(value: object = _UNSET) -> str:
    """Resolve the configured backend, defaulting to ``mock`` when unset/empty.

    An unrecognized non-empty value is a configuration error and raises (mirrors
    :func:`toee_hermes.drivers.base.resolve_integration_driver`, ADR-0137).
    """
    if value is _UNSET:
        value = os.environ.get(TOOL_BACKEND_ENV)

    if value is None or value == "":
        return "mock"

    if value in KNOWN_BACKENDS:
        return value  # type: ignore[return-value]

    raise ValueError(
        f'Unknown {TOOL_BACKEND_ENV} "{value}". '
        f"Expected one of: {', '.join(KNOWN_BACKENDS)}."
    )


def memory_enabled(value: object = _UNSET) -> bool:
    """Whether Customer Memory is active for this deployment (S05, FR-7/RK-6).

    True only when the datastore backend is configured (``TOOL_BACKEND=datastore``).
    Single source of truth shared by the write overlay (S04's per-tool
    ``extra_drivers`` injection) and the read injection gates (S07/S08): a
    mock/unset deployment never hard-depends on Postgres — reads inject nothing,
    writes stay on the ephemeral mock, and the turn still completes and replies.
    """
    return resolve_tool_backend(value) == "datastore"


# Shared with hermes_runtime.gateway_composition.resolve_reply_sender (S01,
# FR-10/NFR-4): "simulated" is the one deployment-wide signal for "this process
# is running the Conversation Simulator, not real customer traffic." Read again
# here rather than importing gateway_composition's constant so the tool-dispatch
# composition root (a separate process/deployment, ADR-0141) never has to import
# the gateway's composition module just for this string.
SIMULATED_MODE_ENV = "REPLY_SENDER"
_SIMULATED_MODE_VALUE = "simulated"


def simulated_mode_enabled(value: object = _UNSET) -> bool:
    """True only when ``REPLY_SENDER=simulated`` (0.0.3 S05, NFR-4 gate reuse).

    Governs dev-only mutation surfaces reachable through tools:dispatch that must
    be impossible in production -- currently ``toee_identity_lookup.link_identity``
    (see ``tool_dispatch_composition._simulated_only_gate``). Fail-closed by
    construction: unset, empty, or any value other than exactly ``"simulated"``
    (case-insensitive) returns ``False``, mirroring
    ``gateway_composition.resolve_reply_sender``'s treatment of that same value.
    """
    if value is _UNSET:
        value = os.environ.get(SIMULATED_MODE_ENV)
    return isinstance(value, str) and value.strip().lower() == _SIMULATED_MODE_VALUE


# Env flag gating the L6 learning loop (0.0.3 S23, FR-22). DISTINCT from
# ``memory_enabled()`` (L4 Customer Memory, ``TOOL_BACKEND``): the post-copilot
# review pass is a separate, opt-in surface, DEFAULT OFF so the eval record/replay
# path (which never sets it) stays byte-identical and deterministic (NFR eval
# gate). This is the single cost knob -- one bounded review pass per copilot turn,
# and only when this is on. S25 formalizes the eval pin + the L6 ADR.
AGENT_EXPERIENCE_ENV = "AGENT_EXPERIENCE_LEARNING"
_AGENT_EXPERIENCE_ON_VALUES = frozenset({"1", "on", "true", "enabled", "yes"})


def _flag_on(env_var: str, value: object = _UNSET) -> bool:
    """Shared fail-closed reader for the L6 and L7 on/off flags (S25 dedup).

    ``value`` defaults to ``os.environ[env_var]``; True only when it is a string
    in the explicit on-set. One implementation so the three agent-experience
    flags below and 0.0.5 S06's two lexicon-injection flags can't drift on
    parsing. (``memory_enabled``/``simulated_mode_enabled`` use different
    discriminators and stay separate.)
    """
    if value is _UNSET:
        value = os.environ.get(env_var)
    return isinstance(value, str) and value.strip().lower() in _AGENT_EXPERIENCE_ON_VALUES


def agent_experience_enabled(value: object = _UNSET) -> bool:
    """Whether the L6 learning-loop review pass runs (0.0.3 S23, FR-22).

    Fail-closed by construction: unset, empty, or any value outside the explicit
    on-set returns ``False`` (mirrors :func:`simulated_mode_enabled`). Its OWN
    axis, never ``memory_enabled()`` -- L6 is on/off independently of the L4
    Customer Memory datastore, and default-off keeps the copilot eval replay
    gate deterministic (the review pass never runs on the record/replay path).
    """
    return _flag_on(AGENT_EXPERIENCE_ENV, value)


# S25 (FR-25/26, NFR-6): confirmed-entry INJECTION flags. INJECTION is a separate
# concern from LEARNING (AGENT_EXPERIENCE_LEARNING gates the propose path): a
# deployment can inject confirmed learnings without running the review pass, and
# vice versa. TWO independent axes so the external read can be disabled WITHOUT
# touching the copilot path (audit finding 5). Both fail-closed / DEFAULT OFF, so
# the eval record/replay path -- which sets neither -- never reads or injects a
# confirmed entry and stays byte-identical (the eval-determinism pin).
AGENT_EXPERIENCE_INJECTION_ENV = "AGENT_EXPERIENCE_INJECTION"  # copilot draft turn
AGENT_EXPERIENCE_EXTERNAL_INJECTION_ENV = "AGENT_EXPERIENCE_EXTERNAL_INJECTION"  # external turn


def agent_experience_injection_enabled(value: object = _UNSET) -> bool:
    """Whether the COPILOT draft turn injects confirmed L6 entries (S25, FR-25).

    Fail-closed by construction (mirrors :func:`agent_experience_enabled`): unset,
    empty, or any value outside the on-set returns ``False``. Its OWN axis, default
    off -- so the copilot eval replay gate stays deterministic."""
    return _flag_on(AGENT_EXPERIENCE_INJECTION_ENV, value)


def agent_experience_external_injection_enabled(value: object = _UNSET) -> bool:
    """Whether the EXTERNAL turn injects confirmed L6 entries read-only (S25, FR-25).

    Fully independent of :func:`agent_experience_injection_enabled` (the copilot
    axis) so the external read is disable-able without touching the copilot path.
    Fail-closed / default off -- the external turn only ever READS confirmed
    learnings and never proposes (S23 kept propose off the external profile)."""
    return _flag_on(AGENT_EXPERIENCE_EXTERNAL_INJECTION_ENV, value)


def load_confirmed_experience(store: Optional[Any]) -> Optional[list[dict[str, Any]]]:
    """Bounded, fail-closed read of CONFIRMED L6 entries for turn injection (S25).

    Shared by both turn seams (copilot ``copilot_turn.py`` + external
    ``openrouter.py``); each caller gates on its OWN injection flag before calling,
    so this only does the read. Operational, NOT customer-scoped (unlike the
    Customer Memory read): L6 learnings are shared team knowledge, so there is no
    binding key.

    Fail-closed, mirroring ``_load_turn_memory``'s philosophy: a store without the
    method (a mock/scenario store), or ANY read error, degrades to ``None`` (no
    learnings injected) and never raises -- L6 injection is never a hard dependency
    of a turn (NFR-5). Only ``status='confirmed'`` rows are ever returned (the store
    method filters); ``proposed``/``rejected`` never reach any turn."""
    resolved_store = store if store is not None else _gateway_store()
    reader = getattr(resolved_store, "load_confirmed_experience", None)
    if reader is None:
        return None
    try:
        return reader()
    except Exception as exc:
        # ponytail: swallow to None so a DB hiccup degrades to "no learnings
        # injected", never a failed turn (NFR-5). Exception TYPE only -- never
        # str(exc), which could echo back store-supplied content.
        logger.warning(
            "Agent-experience injection read failed error_type=%s; "
            "turn continues with no confirmed learnings injected",
            type(exc).__name__,
        )
        return None


# --------------------------------------------------------------------------- #
# L7 semantic lexicon: the glossary bound + the two injection flags (0.0.5 S06)
# --------------------------------------------------------------------------- #

# D16: a NAMED constant from day one, not a literal buried in the selection
# query. S22's knob panel renders "glossary N" by importing this name; a bare
# `20` inside postgres_gateway_store would make that a magic-number hunt. Reading
# it from deploy-time config later is a one-line change here and nowhere else
# (D14 -- the knob moves by config commit, never by an in-app mutation path).
#
# The BOUND is fixed; what fills it is now a knob (S26 -- see below).
LEXICON_GLOSSARY_LIMIT = 20

# 0.0.5 S26, FR-6's upgrade clause: WHICH confirmed entries fill those 20 seats.
#
#   newest (DEFAULT) -- newest-decided first, S06's shipped behaviour, unchanged.
#   health           -- ranked by S26's entry-health score, round-robin across
#                       entry kinds so a `default_rule` (which earns no hit_count
#                       at all) cannot be starved by a domain full of aliases.
#
# The default stays `newest` until the scores stabilize, exactly as the slice
# asks: `health` reads a table that is empty until the judge job and the ledger
# have both run, and ranking on an empty table would reorder the prompt for no
# information. Flipping it is a DEPLOY-TIME CONFIG COMMIT (D14): there is no
# in-app mutation path for any knob in 0.0.5, the panel displays values and never
# changes them, and the audit trail for the flip is git history. Saying that
# plainly is the honest version -- a UI that looks mutable and is not would be
# worse than no UI.
LEXICON_SELECTION_ENV = "LEXICON_SELECTION"
LEXICON_SELECTION_NEWEST = "newest"
LEXICON_SELECTION_HEALTH = "health"
LEXICON_SELECTION_STRATEGIES = (LEXICON_SELECTION_NEWEST, LEXICON_SELECTION_HEALTH)


def lexicon_selection_strategy(value: object = _UNSET) -> str:
    """Which glossary selection strategy is live (FR-6 upgrade clause, S26).

    Fail-SAFE rather than fail-closed, and the difference matters: an unknown or
    unset value returns the shipped `newest` behaviour instead of an error or a
    silent no-glossary, because a typo'd knob must never be able to empty the
    prompt. Only the exact literal `health` flips it.
    """
    raw = os.environ.get(LEXICON_SELECTION_ENV) if value is _UNSET else value
    text = str(raw).strip().lower() if raw is not None else ""
    return LEXICON_SELECTION_HEALTH if text == LEXICON_SELECTION_HEALTH else (
        LEXICON_SELECTION_NEWEST
    )

# TWO independent axes, the S25-0.0.3 two-flag precedent: the external read must
# be disable-able WITHOUT touching the copilot path, and vice versa. Both
# fail-closed / DEFAULT OFF, so the eval record/replay path -- which sets
# neither -- never reads or renders a lexicon entry and the injected prompt stays
# byte-identical (the eval-determinism pin, NFR-4).
LEXICON_INJECTION_ENV = "LEXICON_INJECTION"  # copilot draft turn
LEXICON_EXTERNAL_INJECTION_ENV = "LEXICON_EXTERNAL_INJECTION"  # external turn


def lexicon_injection_enabled(value: object = _UNSET) -> bool:
    """Whether the COPILOT draft turn injects the confirmed L7 glossary (S06, FR-6).

    Fail-closed by construction (mirrors :func:`agent_experience_injection_enabled`):
    unset, empty, or any value outside the on-set returns ``False``. Its OWN axis,
    default off -- so the copilot eval replay gate stays deterministic."""
    return _flag_on(LEXICON_INJECTION_ENV, value)


def lexicon_external_injection_enabled(value: object = _UNSET) -> bool:
    """Whether the EXTERNAL turn injects the confirmed L7 glossary (S06, FR-6).

    Fully independent of :func:`lexicon_injection_enabled` (the copilot axis) so
    the external read is disable-able without touching the copilot path.
    Fail-closed / default off; the glossary is read-only on both paths -- neither
    turn proposes lexicon entries."""
    return _flag_on(LEXICON_EXTERNAL_INJECTION_ENV, value)


# 0.0.5 S04 (FR-4): the CAPTURE axis for L7 -- whether a post-turn fork may
# propose a lexicon entry at all. Deliberately NOT either injection flag above:
# INJECTION reads confirmed vocabulary into a prompt, CAPTURE writes a proposal
# into the queue, and a deployment may legitimately want one without the other
# (the L6 precedent, where AGENT_EXPERIENCE_LEARNING is separate from its two
# injection flags for exactly this reason).
#
# DEFAULT OFF, and that is the eval-determinism pin (NFR-4): the record/replay
# path sets no flag, so the gateway turn enqueues nothing and its result stays
# byte-identical. It is also the cost knob -- one bounded fork per captured turn.
LEXICON_CAPTURE_ENV = "LEXICON_CAPTURE"


def lexicon_capture_enabled(value: object = _UNSET) -> bool:
    """Whether the L7 capture forks may propose lexicon entries (S04, FR-4).

    Fail-closed by construction (mirrors :func:`agent_experience_enabled`): unset,
    empty, or any value outside the explicit on-set returns ``False``. Gates BOTH
    forks -- the gateway-side capture fork's enqueue and the copilot review fork's
    lexicon leg -- because a default-OFF that covered only one of them would leave
    the other advertising a destination the deployment had disabled."""
    return _flag_on(LEXICON_CAPTURE_ENV, value)


# 0.0.5 S16 (FR-23): copilot triage annotations, DEFAULT OFF on its own axis.
# Two things ride on the default rather than on anyone's discipline. It is a
# COST knob -- every annotated item is one billed completion, and the other half
# of the spend is `copilot_triage.TRIAGE_BATCH_CAP` x the schedule interval in
# `background_worker.COPILOT_TRIAGE_INTERVAL_SECONDS`. And it keeps the eval
# record/replay path exactly where it already is: that path sets no flag and
# runs no background worker, so with this unset there is no annotator, no model
# call and nothing new on any turn (NFR-4). Nothing about the annotator touches
# a turn even when it IS on -- it reads a queue and writes advisory metadata --
# so the flag is the deployment's cost switch, not an eval-determinism patch.
COPILOT_TRIAGE_ENV = "COPILOT_TRIAGE_ANNOTATIONS"


def copilot_triage_enabled(value: object = _UNSET) -> bool:
    """Whether the copilot triage annotator runs at all (0.0.5 S16, FR-23).

    Fail-closed by construction (mirrors :func:`lexicon_injection_enabled`):
    unset, empty, or any value outside the explicit on-set returns ``False``.
    Gates BOTH halves of FR-23 -- the scheduled batch and the per-item on-demand
    action -- because "default OFF" that only covered the schedule would leave a
    button in the console spending money on a deployment that disabled the
    feature."""
    return _flag_on(COPILOT_TRIAGE_ENV, value)


def load_confirmed_lexicon(store: Optional[Any]) -> Optional[list[dict[str, Any]]]:
    """Bounded, fail-closed read of CONFIRMED L7 entries for turn injection (S06).

    The L7 mirror of :func:`load_confirmed_experience`, deliberately identical in
    posture: shared by both turn seams, each caller gates on its OWN injection
    flag before calling, operational rather than customer-scoped (domain language
    is shared, so there is no binding key), and fail-closed -- a store without the
    method (a mock/scenario store) or ANY read error degrades to ``None`` and
    never raises, because L7 injection is never a hard dependency of a turn
    (NFR-5). Only ``status='confirmed'`` rows are ever returned (the store method
    filters, and ``hooks._render_lexicon`` re-checks); ``proposed``/``rejected``/
    ``retired`` never reach any turn.
    """
    resolved_store = store if store is not None else _gateway_store()
    reader = getattr(resolved_store, "load_confirmed_lexicon", None)
    if reader is None:
        return None
    try:
        return reader()
    except Exception as exc:
        # ponytail: swallow to None so a DB hiccup degrades to "no glossary
        # injected", never a failed turn (NFR-5). Exception TYPE only -- never
        # str(exc), which could echo back store-supplied content.
        logger.warning(
            "Lexicon glossary injection read failed error_type=%s; "
            "turn continues with no confirmed lexicon injected",
            type(exc).__name__,
        )
        return None


def record_memory_injection_metric(flag: bool) -> None:
    """Fire-and-forget memory-injection counter emit (0.0.3 S26, FR-28 gap #1).

    Shared by both turn seams (``openrouter.py``/``copilot_turn.py``); each
    caller passes ``bool(memory)`` -- the raw Customer Memory slot list, NOT
    the combined injection block (which also includes the Session Identity
    Snapshot / L6 learnings) -- so the counter measures L4 Customer Memory
    injection specifically, per FR-28's "memory injection rate".

    Gated on :func:`memory_enabled` -- the SAME axis the feature itself is
    gated on -- so a mock/unset deployment (the vast majority of unit/eval
    runs) never attempts a metrics DB connection; the emit itself
    (:func:`hermes_runtime.metrics.emit_metric_event`) is separately
    turn-safe (never raises) for the datastore-backend case too."""
    if not memory_enabled():
        return
    emit_metric_event(MEMORY_INJECTION, flag)


def select_tool_driver(backend: Optional[str] = None) -> ToolDriver:
    """Build the dispatch ToolDriver for ``backend`` (env-resolved when ``None``).

    Mock-first: returns a MockDriver unless ``datastore`` is selected, in which
    case a :class:`~hermes_runtime.datastore.driver.PostgresDriver` is built. The
    Postgres driver resolves its DSN lazily and only connects inside ``execute``,
    so constructing it never requires a reachable database.
    """
    resolved = resolve_tool_backend(_UNSET if backend is None else backend)
    if resolved == "datastore":
        from hermes_runtime.datastore.driver import PostgresDriver

        return PostgresDriver()
    return MockDriver(create_all_mock_handlers())


def _customer_memory_extra_drivers() -> Optional[dict[str, Any]]:
    """Route ``toee_customer_memory`` to the Postgres datastore for an agent turn.

    Shared by the live External turn (``openrouter.py``, S04) and the unbound
    Copilot draft turn (``copilot_turn.py``, S20/PAC-4 gap #2) -- both boot paths
    need the SAME overlay, so it lives here next to the two things it uses
    (:func:`memory_enabled`, :func:`select_tool_driver`) instead of being
    reimplemented per caller (Standards fix #1). Gated by :func:`memory_enabled`
    (S05) -- the single source of truth for whether Customer Memory is active,
    shared with the read injection gates (S07/S08). ``False`` (mock/unset
    backend) returns ``None`` so the tool stays on the shared mock driver and a
    mock deployment never hard-depends on Postgres. ``select_tool_driver`` builds
    the ``PostgresDriver`` (psycopg stays in hermes-runtime); the plugin overlay
    only ever sees a ``ToolDriver``, whose ``kind = "datastore"`` attributes the
    audit rows (anti-mock, ADR-0140).
    """
    if not memory_enabled():
        return None
    return {"toee_customer_memory": select_tool_driver("datastore")}


def _knowledge_extra_drivers() -> Optional[dict[str, Any]]:
    """Route ``toee_knowledge_search`` to the S08 retriever for an agent turn.

    The knowledge twin of :func:`_customer_memory_extra_drivers`: same
    ``extra_drivers`` seam (§7 seam 4), same shape, gated by its own axis
    (:func:`hermes_runtime.knowledge.driver.knowledge_enabled`, ``KNOWLEDGE_BACKEND``)
    rather than :func:`memory_enabled`'s ``TOOL_BACKEND`` -- knowledge is on/off
    independently of the business datastore. ``False`` (unset/off) returns
    ``None`` so the tool stays on the shared mock driver's 2-entry stub and a
    deployment without a knowledge store never hard-depends on it.

    Not called from any turn composition path yet (S10 wires it onto the
    external/copilot turn profiles); this only builds the overlay dict.
    """
    from hermes_runtime.knowledge.driver import KnowledgeDriver, knowledge_enabled

    if not knowledge_enabled():
        return None
    return {"toee_knowledge_search": KnowledgeDriver()}


def _agent_experience_extra_drivers() -> Optional[dict[str, Any]]:
    """Route ``toee_agent_experience`` to the Postgres datastore for the review fork.

    The L6 twin of :func:`_customer_memory_extra_drivers` / :func:`_knowledge_extra_drivers`:
    same ``extra_drivers`` seam, same shape, but gated on its OWN axis
    (:func:`agent_experience_enabled`, ``AGENT_EXPERIENCE_LEARNING``) -- NOT
    ``memory_enabled()``. ``False`` (default) returns ``None`` so a
    ``propose_experience`` call stays on the shared mock driver and is discarded,
    and a deployment with the loop off never hard-depends on Postgres. This is
    wired ONLY into the S23 review fork's turn composition (``copilot_turn._run_review_pass``),
    never the main draft turn's :func:`_turn_extra_drivers` -- the draft agent
    never proposes experiences; only the review fork does. ``select_tool_driver``
    builds the ``PostgresDriver`` whose ``kind = "datastore"`` attributes the
    audit rows (anti-mock, ADR-0140).
    """
    if not agent_experience_enabled():
        return None
    return {"toee_agent_experience": select_tool_driver("datastore")}


def _lexicon_capture_extra_drivers() -> Optional[dict[str, Any]]:
    """Route ``toee_semantic_lexicon`` to Postgres for a capture fork (0.0.5 S04).

    The L7 twin of :func:`_agent_experience_extra_drivers`, same seam and same
    shape, gated on its OWN axis (:func:`lexicon_capture_enabled`,
    ``LEXICON_CAPTURE``) -- not ``memory_enabled()`` and not either L7 INJECTION
    flag. ``False`` (default) returns ``None``, so a ``propose_lexicon_entry``
    call stays on the shared mock driver and is discarded, and a deployment with
    capture off never hard-depends on Postgres.

    Wired ONLY into the two forks (:func:`hermes_runtime.lexicon_capture.run_l7_capture_job`
    and ``copilot_turn._run_review_pass``), never into a turn's
    :func:`_turn_extra_drivers` -- neither the external agent nor the copilot
    draft agent proposes vocabulary; only a fork does. That separation is the
    whole point of ADR-0152's superseding note.
    """
    if not lexicon_capture_enabled():
        return None
    return {"toee_semantic_lexicon": select_tool_driver("datastore")}


def _turn_extra_drivers(*, include_memory_write: bool = True) -> Optional[dict[str, Any]]:
    """Merge the Customer Memory and Knowledge per-tool overlays for one agent turn.

    Single source for both turn paths (external ``openrouter.py`` + copilot draft
    ``copilot_turn.py``, S10): each overlay is gated on its own independent axis
    (:func:`memory_enabled`'s ``TOOL_BACKEND`` vs
    :func:`hermes_runtime.knowledge.driver.knowledge_enabled`'s ``KNOWLEDGE_BACKEND``),
    mirroring how the two gates already stay independent -- no coupling introduced
    by merging them here. ``None`` only when BOTH overlays are off, so a turn with
    neither backend enabled boots with ``extra_drivers=None`` exactly as before.

    ``include_memory_write`` (S13, FR-14 -- the S20 reversal, ADR-0150): the
    copilot draft turn boots with ``include_memory_write=False`` so
    ``toee_customer_memory`` is left OUT of the merged overlay regardless of
    ``memory_enabled()`` -- the tool stays on the shared mock driver, so an
    agent-initiated ``upsert_preference`` from an unbound draft turn is never
    persisted (it lands in the ephemeral mock and is discarded, same as a
    disabled backend). The Knowledge overlay is unaffected -- it is gated on its
    own independent axis and merges in either way. The external turn
    (``openrouter.py``) keeps calling this with no arguments, so the default
    ``True`` leaves its write path untouched. Memory READS are untouched by this
    flag entirely: the copilot turn's read-injection (``copilot_turn._load_case_memory``)
    goes through the gateway store directly, never through this overlay.
    """
    mem = _customer_memory_extra_drivers() if include_memory_write else None
    kn = _knowledge_extra_drivers()
    if mem is None and kn is None:
        return None
    return {**(mem or {}), **(kn or {})}


def _gateway_store() -> Any:
    """Build the Postgres gateway store for a Customer Memory read/merge/lookup.

    Shared by the turn-time memory read + provisional merge (``openrouter.py``,
    S06/S07/S10), the Copilot case-identity/memory read (``copilot_turn.py``,
    S08), and the Workbench dispatch-time case identity lookup
    (``tool_dispatch_app.py``, S16) -- every caller wants the SAME default
    construction, only ever overridden by an explicit ``store=`` param in tests
    (Standards fix #1). Deferred import keeps ``psycopg`` out of a mock
    deployment's import path (same reasoning as ``select_tool_driver``'s
    ``PostgresDriver`` branch above). Most call sites reach this only under
    :func:`memory_enabled`; the S25 L6 confirmed-experience read reaches it on
    its OWN injection-flag axis instead, but its fail-closed wrapper
    (:func:`load_confirmed_experience`) swallows any resulting connection failure
    (NFR-5), so a mock/unset deployment still never fails a turn on it.
    DSN-based, matching how ``select_tool_driver`` obtains its datastore driver.
    """
    from hermes_runtime.postgres_gateway_store import PostgresGatewayStore

    return PostgresGatewayStore()

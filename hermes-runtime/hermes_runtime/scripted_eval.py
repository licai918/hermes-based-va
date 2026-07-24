"""Scripted-eval turn seam: a real dispatch/gateway turn with a deterministic model (S18, FR-26).

The live agent eval harness (:mod:`hermes_runtime.scripted_gateway_harness`) proves the
turn PIPELINE, not just the replay parser: it POSTs a scenario's inbound webhook to the
running gateway, lets the durable queue + turn-worker run the turn, and reads the reply
back. To keep that turn deterministic and free of any OpenRouter call, the model is
scripted — but the scripted completions must reach the RUNNING turn-worker process, which
the harness cannot inject in-process. This module is that wire-level seam.

The channel is the shared datastore (``scripted_eval_turn``, migration 0016): the harness
seeds one row per scenario keyed by the event id it is about to POST, and the turn-worker
reads it inside :func:`make_scripted_eval_run_turn`'s ``run_turn`` — the SAME model boundary
production fills with :func:`hermes_runtime.openrouter.make_openrouter_run_turn`. Everything
around the model is real: the webhook fast-ack, the durable job, the worker claim, the
context reload + binding check, the governed agent loop, the External Tool Gate, the
transcript capture, the simulated-sender delivery, and the ``message_turn`` mirror. The two
things faked are the model (scripted) and the tool vendor (the scenario's MockDriver) — the
exact two boundaries the Launch Eval recorder already fakes (:mod:`hermes_runtime.eval_record`),
so the captured transcript reproduces the recorded fixture and the existing assertion
package passes unchanged.

PROD-INERT (the top risk of this slice). A seam that injects predetermined agent replies
must be impossible to trigger on a real customer turn:

* it is OFF by default — ``EVAL_SCRIPTED_MODE`` unset means ``resolve_turn_collaborators``
  never builds this run_turn and never reads ``scripted_eval_turn``;
* :func:`require_scripted_eval_prod_inert` REFUSES to arm when ``DEPLOY_ENVIRONMENT`` is a
  production environment, so a prod revision that set the flag fails closed at boot;
* defense in depth, the eval fixtures the run_turn loads (``eval/scenarios``) are not copied
  into the prod image, so even a mis-armed prod worker has nothing to run.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, NamedTuple, Optional, Sequence

# EVAL_SCRIPTED_MODE arms the seam. Off/unset is the production default.
SCRIPTED_MODE_ENV = "EVAL_SCRIPTED_MODE"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Kept in step with gateway_composition's own prod check (duplicated, not imported,
# so this module never imports gateway_composition -- that module imports this one).
_DEPLOY_ENV = "DEPLOY_ENVIRONMENT"
_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod", "staging"})

# The eval fixtures live at the repo-root ``eval/`` dir; resolve from the package
# location (mirrors eval_runner.cli._DEFAULT_EVAL_DIR). Absent from the prod image.
_DEFAULT_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def scripted_eval_armed() -> bool:
    """Whether the scripted-eval seam is armed (``EVAL_SCRIPTED_MODE`` truthy)."""
    return (os.environ.get(SCRIPTED_MODE_ENV) or "").strip().lower() in _TRUTHY


def require_scripted_eval_prod_inert() -> None:
    """Refuse to arm the scripted seam in a production config (fail-closed).

    Called by :func:`resolve_turn_collaborators` only when the seam is armed, so a
    prod revision that set ``EVAL_SCRIPTED_MODE`` raises at boot rather than serving
    real customer turns against injected agent replies.
    """
    environment = (os.environ.get(_DEPLOY_ENV) or "").strip().lower()
    if environment in _PRODUCTION_ENVIRONMENTS:
        raise ValueError(
            f"{SCRIPTED_MODE_ENV} must never be armed in a production environment "
            f"({_DEPLOY_ENV}={environment!r}): the scripted-eval seam injects "
            "predetermined agent replies and is for the eval harness only. Unset "
            f"{SCRIPTED_MODE_ENV}."
        )


# --------------------------------------------------------------------------- #
# Datastore handshake (the one channel from harness process -> turn-worker).
# --------------------------------------------------------------------------- #


class ScriptedTurnRow(NamedTuple):
    suite: str
    scenario_id: str
    completions: list[Mapping[str, Any]]


def seed_scripted_turn(
    conn: Any,
    *,
    event_id: str,
    suite: str,
    scenario_id: str,
    completions: Sequence[Mapping[str, Any]],
) -> None:
    """Seed the scripted completions for ``event_id`` before its inbound is POSTed."""
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scripted_eval_turn (event_id, suite, scenario_id, completions)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (event_id) DO UPDATE SET
                suite = EXCLUDED.suite,
                scenario_id = EXCLUDED.scenario_id,
                completions = EXCLUDED.completions,
                captured = NULL,
                captured_at = NULL,
                created_at = now()
            """,
            (event_id, suite, scenario_id, Jsonb(list(completions))),
        )
    conn.commit()


def load_scripted_turn(conn: Any, event_id: str) -> Optional[ScriptedTurnRow]:
    """Load the seeded scenario + completions for ``event_id`` (None when unseeded)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT suite, scenario_id, completions FROM scripted_eval_turn WHERE event_id = %s",
            (event_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ScriptedTurnRow(suite=row[0], scenario_id=row[1], completions=row[2])


def save_captured_turn(conn: Any, event_id: str, captured: Mapping[str, Any]) -> None:
    """Persist the captured ``{final_response, messages}`` turn for the harness to read."""
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scripted_eval_turn SET captured = %s, captured_at = %s WHERE event_id = %s",
            (Jsonb(dict(captured)), datetime.now(timezone.utc), event_id),
        )
    conn.commit()


def load_captured_turn(conn: Any, event_id: str) -> Optional[dict[str, Any]]:
    """Read back the captured turn for ``event_id`` (None until the worker ran it)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT captured FROM scripted_eval_turn WHERE event_id = %s AND captured IS NOT NULL",
            (event_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


# --------------------------------------------------------------------------- #
# Transcript -> scripted completions (the harness seeds these).
# --------------------------------------------------------------------------- #


def scripted_completions_from_transcript(
    messages: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Derive the scripted model completions from a recorded transcript's assistant turns.

    Each assistant message becomes one completion the scripted provider serves in order:
    a ``tool_calls`` message -> ``{"tool_calls": [{name, arguments}]}`` (arguments parsed
    back to a dict); a plain message -> ``{"content": ...}``. This is the inverse of
    :func:`hermes_runtime.live._completion_from_spec`, so re-running the loop against the
    scenario's MockDriver reproduces the recorded transcript (determinism, no model).
    """
    import json

    specs: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            calls: list[dict[str, Any]] = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except (TypeError, ValueError):
                    args = {}
                calls.append({"name": fn.get("name") or "", "arguments": args})
            specs.append({"tool_calls": calls})
        else:
            specs.append({"content": msg.get("content") or ""})
    return specs


# --------------------------------------------------------------------------- #
# The run_turn seam (the model boundary the turn-worker fills when armed).
# --------------------------------------------------------------------------- #


class ScriptedTurnNotSeeded(RuntimeError):
    """Raised when a turn runs in scripted mode but no completions were seeded for it.

    Fail-loud, never fall through to a model: a scripted-mode worker that reaches a
    turn with no seeded row is a harness bug, not a cue to call OpenRouter.
    """


@contextmanager
def _pool_connection() -> Iterator[Any]:
    from hermes_runtime.datastore.pool import get_database_pool

    with get_database_pool().connection() as conn:
        yield conn


def make_scripted_eval_run_turn(
    *,
    eval_dir: Any = _DEFAULT_EVAL_DIR,
    connect: Optional[Callable[[], Any]] = None,
    record_dir: Any = None,
) -> Callable[[Any, str], Mapping[str, Any]]:
    """Build the scripted-eval ``run_turn`` (the model boundary, deterministic, no OpenRouter).

    The returned ``(context, inbound_body)`` callable reads the completions seeded for
    ``context.event_id``, boots the External profile with the scenario's MockDriver + Tool
    Gate + Session Identity Snapshot (:func:`hermes_runtime.boot.boot_profile_eval`, the
    recorder's boot), runs one real ``AIAgent`` loop against the scripted provider, writes
    the captured ``{final_response, messages}`` transcript back to the seed row, and returns
    it — the exact shape :func:`hermes_runtime.turn_runner.make_gateway_turn_runner` derives
    the reply from. ``inbound_body`` is ignored: the scenario defines the turn (its multi-turn
    text + injected identity/memory block, via ``scenario_user_message``), so the captured
    transcript matches the recorded fixture regardless of the placeholder webhook body.

    ``connect`` yields the datastore connection (defaults to the process pool); ``record_dir``,
    when given, also persists each captured transcript to disk in the replay layout (the S19
    recorder seam).
    """
    connect_cm = _pool_connection if connect is None else _as_cm(connect)

    def run_turn(context: Any, inbound_body: str) -> Mapping[str, Any]:
        # Lazy imports: the eval machinery is only touched when a scripted turn actually
        # runs (armed + seeded), so a normal boot never imports it -- reinforcing prod-inertness.
        from eval_runner.fixtures import load_scenario
        from eval_runner.harness import create_scenario_driver, scenario_tool_gate
        from toee_hermes.plugin.profiles import EXTERNAL

        from hermes_runtime.boot import boot_profile_eval
        from hermes_runtime.eval_record import scenario_user_message
        from hermes_runtime.live import run_scripted_agent

        event_id = context.event_id
        with connect_cm() as conn:
            row = load_scripted_turn(conn, event_id)
            if row is None:
                raise ScriptedTurnNotSeeded(
                    f"no scripted_eval_turn row for event_id={event_id!r}; "
                    "the harness must seed completions before POSTing the inbound."
                )
            scenario = load_scenario(row.suite, row.scenario_id, eval_dir)
            driver = create_scenario_driver(scenario.mock_context)
            gate = scenario_tool_gate(scenario)
            booted = boot_profile_eval(
                EXTERNAL, driver=driver, gate=gate, identity=scenario.session_identity
            )
            turn = run_scripted_agent(
                user_message=scenario_user_message(scenario),
                scripted_completions=list(row.completions),
                governed_tool_names=booted.tool_names,
            )
            save_captured_turn(conn, event_id, turn)

        if record_dir is not None:
            from eval_runner.recorder import record_turn

            record_turn(turn=turn, scenario=scenario, transcripts_dir=record_dir)
        return turn

    return run_turn


def _as_cm(connect: Callable[[], Any]) -> Callable[[], Any]:
    """Adapt a plain ``connect()`` (returning a connection) into a no-close context manager.

    Lets tests pass the throwaway-schema fixture connection straight through without the
    factory closing it.
    """

    @contextmanager
    def cm() -> Iterator[Any]:
        yield connect()

    return cm

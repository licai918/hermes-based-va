"""Live agent eval harness: drive a REAL turn through the dispatch/gateway path (S18, FR-26).

This is the harness FR-26 asks for -- it replaces ``eval_runner._StubAgentHarness`` in the
CI gate with one that proves the PIPELINE, not just the replay parser. For each scenario it:

  1. derives the scripted model completions from the recorded transcript (the inverse of
     the recorder), and seeds them on the datastore keyed by the event id it will POST;
  2. POSTs the scenario's inbound webhook to the running gateway -- from here the real
     pipeline runs: fast-ack, durable job, turn-worker claim, context reload + binding
     check, the governed agent loop against the scripted provider (no OpenRouter), the
     simulated-sender delivery, and the ``message_turn`` mirror;
  3. reads the reply back -- confirms the mirror landed in ``message_turn`` and reads the
     captured transcript the worker persisted -- and maps it to an ``AgentTurnResult`` for
     the EXISTING assertion package (:func:`eval_runner.assertions.evaluate_scenario`),
     via the same :func:`eval_runner.turn_result.build_scenario_turn_result` the replay
     harness uses. No assertion is rewritten.

The worker half of the seam (arming, prod-inertness, the scripted run_turn) lives in
:mod:`hermes_runtime.scripted_eval`; this module is the harness/driver half and the CLI the
CI job runs. Determinism (NFR-6): the completions and the scenario MockDriver are both fixed,
so two runs are byte-stable on the assertions -- ``main`` runs the suite twice and fails on
any drift.

Run it against a booted stack (``node scripts/dev-up.mjs --stack-only`` with the turn-worker
armed via ``EVAL_SCRIPTED_MODE=1``)::

    uv run --frozen python -m hermes_runtime.scripted_gateway_harness \
        --suite text_first_launch --gateway-url http://gateway:8080
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence

from eval_runner.assertions import evaluate_scenario
from eval_runner.fixtures import load_suite
from eval_runner.report import ScenarioOutcome, build_report
from eval_runner.turn_result import build_scenario_turn_result
from eval_runner.types import MergedScenario

from hermes_runtime.scripted_eval import (
    load_captured_turn,
    load_scripted_turn,
    scripted_completions_from_transcript,
    seed_scripted_turn,
)

_DEFAULT_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
_DEFAULT_GATEWAY_URL = "http://127.0.0.1:8080"
_DEFAULT_WEBHOOK_TOKEN = "dev-webhook-token"
_DEFAULT_POLL_TIMEOUT = 60.0

# The customer channels the SMS/email gateway actually serves. A scenario on any other
# channel (e.g. "internal_copilot") is NOT a gateway turn -- it runs on the dispatch-copilot
# server via the workbench BFF, not the SMS webhook -- so this harness skips it and the
# additive replay gate (eval_runner --harness replay) keeps covering it.
_GATEWAY_CHANNELS = frozenset({"simpletexting", "email", "simulated_email"})


def is_gateway_scenario(scenario: MergedScenario) -> bool:
    """Whether ``scenario`` is a customer turn the dispatch/gateway path can drive."""
    return scenario.channel in _GATEWAY_CHANNELS


class HarnessError(RuntimeError):
    """A pipeline fault the harness observed (never a scenario assertion failure)."""


def _inbound_text(scenario: MergedScenario) -> str:
    """A placeholder webhook body from the scenario's inbound turns.

    The scripted run_turn ignores the webhook body (the scenario defines the turn), but a
    realistic body still lands in the inbound ``message_turn`` row and keeps logs readable.
    """
    parts: list[str] = []
    for turn in scenario.turns:
        inbound = turn.inbound
        parts.append(inbound.get("body", "") if isinstance(inbound, dict) else str(inbound))
    return "\n\n".join(p for p in parts if p) or "eval scripted turn"


def _contact_phone(scenario: MergedScenario) -> str:
    """A per-scenario E.164 so each scenario gets its own customer thread (no collision)."""
    try:
        n = int(scenario.scenario_id)
    except ValueError:
        # Stable across processes: builtin hash() is salted per-process for str, a
        # latent footgun in a determinism-critical harness. sha1 is fixed.
        n = int(hashlib.sha1(scenario.scenario_id.encode()).hexdigest(), 16)
    return f"+1416555{n % 10000:04d}"


class ScriptedGatewayHarness:
    """An ``AgentHarness`` that drives each scenario through the running gateway pipeline."""

    def __init__(
        self,
        *,
        gateway_url: str = _DEFAULT_GATEWAY_URL,
        webhook_token: str = _DEFAULT_WEBHOOK_TOKEN,
        transcripts_dir: Any,
        record_dir: Any = None,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        connect: Optional[Any] = None,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.webhook_token = webhook_token
        self.transcripts_dir = Path(transcripts_dir)
        self.record_dir = Path(record_dir) if record_dir is not None else None
        self.poll_timeout = poll_timeout
        self._connect = connect  # test seam; defaults to the process pool

    # -- datastore access ------------------------------------------------- #

    def _connection(self):
        if self._connect is not None:
            from contextlib import nullcontext

            return nullcontext(self._connect())
        from hermes_runtime.datastore.pool import get_database_pool

        return get_database_pool().connection()

    # -- pipeline steps --------------------------------------------------- #

    def _completions_for(self, scenario: MergedScenario) -> list[dict[str, Any]]:
        path = self.transcripts_dir / scenario.suite / f"{scenario.scenario_id}.json"
        if not path.is_file():
            raise HarnessError(
                f"no recorded transcript to script scenario '{scenario.scenario_id}' at {path}"
            )
        doc = json.loads(path.read_text(encoding="utf-8"))
        return scripted_completions_from_transcript(doc.get("messages") or [])

    def _post_inbound(self, scenario: MergedScenario, event_id: str) -> None:
        body = {
            "type": "INCOMING_MESSAGE",
            "reportId": event_id,
            "webhookId": "scripted-gateway-harness",
            "values": {
                "messageId": event_id,
                "text": _inbound_text(scenario),
                "accountPhone": "+15005550000",
                "contactPhone": _contact_phone(scenario),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }
        url = f"{self.gateway_url}/webhooks/simpletexting?token={self.webhook_token}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                raise HarnessError(
                    f"gateway webhook returned {resp.status} (expected 200 fast-ack)"
                )

    def _poll_captured(self, event_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            with self._connection() as conn:
                captured = load_captured_turn(conn, event_id)
            if captured is not None:
                return captured
            if time.monotonic() > deadline:
                raise HarnessError(
                    f"turn for event {event_id} never captured within {self.poll_timeout}s "
                    "(turn-worker armed with EVAL_SCRIPTED_MODE and claiming jobs?)"
                )
            time.sleep(0.5)

    def _reply_mirrored(self, conn: Any, event_id: str) -> bool:
        """Whether the pipeline mirrored a customer-facing reply into ``message_turn``.

        The outbound row id is ``<session_id>:<event_id>:out`` (postgres_gateway_store); a
        non-empty hermes outbound body for this event proves the simulated send + mirror ran.
        """
        with conn.cursor() as cur:
            cur.execute(
                "SELECT body FROM message_turn "
                "WHERE id LIKE %s AND direction = 'outbound' AND author = 'hermes'",
                (f"%:{event_id}:out",),
            )
            row = cur.fetchone()
        return bool(row and (row[0] or "").strip())

    def _wait_for_reply(self, event_id: str) -> None:
        """Poll ``message_turn`` for the mirrored reply (the true end-of-pipeline signal).

        The worker commits the captured transcript BEFORE it delivers the reply, so the
        mirror lands strictly after capture -- gating on capture alone races the mirror.
        """
        deadline = time.monotonic() + self.poll_timeout
        while True:
            with self._connection() as conn:
                if self._reply_mirrored(conn, event_id):
                    return
            if time.monotonic() > deadline:
                raise HarnessError(
                    f"turn for event {event_id} captured a transcript but no reply landed "
                    "in message_turn within "
                    f"{self.poll_timeout}s (delivery/mirror path broken)."
                )
            time.sleep(0.5)

    # -- AgentHarness ----------------------------------------------------- #

    def run_turn(self, scenario: MergedScenario):
        completions = self._completions_for(scenario)
        event_id = f"eval-{scenario.suite}-{scenario.scenario_id}-{uuid.uuid4().hex[:8]}"

        with self._connection() as conn:
            seed_scripted_turn(
                conn,
                event_id=event_id,
                suite=scenario.suite,
                scenario_id=scenario.scenario_id,
                completions=completions,
            )

        self._post_inbound(scenario, event_id)
        captured = self._poll_captured(event_id)

        result = build_scenario_turn_result(
            scenario,
            final_response=captured.get("final_response", "") or "",
            messages=list(captured.get("messages", []) or []),
        )

        # Reading the reply back from message_turn is the pipeline proof the slice exists
        # for: REPLY_SENDER=simulated skipped the provider POST but still mirrored the reply.
        # A turn that produced no customer-facing text (nothing to deliver) writes no row --
        # only assert the mirror when the turn actually replied.
        if result.outbound_text.strip():
            self._wait_for_reply(event_id)

        if self.record_dir is not None:
            from eval_runner.recorder import record_turn

            record_turn(turn=captured, scenario=scenario, transcripts_dir=self.record_dir)

        return result


# --------------------------------------------------------------------------- #
# CLI: run the suite twice and prove byte-stable determinism.
# --------------------------------------------------------------------------- #


def _assertion_signature(report) -> list[dict[str, Any]]:
    """A byte-comparable digest of a run's outcome (order-stable).

    A flipped assertion changes ``passed`` or the ``failed_assertions`` set for its
    scenario, so comparing this across runs catches any nondeterminism.
    """
    return [
        {
            "scenario_id": s.scenario_id,
            "passed": s.passed,
            "failed": sorted((f.type, f.name, f.detail) for f in s.failed_assertions),
        }
        for s in report.scenarios
    ]


def _print_report(label: str, report) -> None:
    summary = report.summary
    for scenario in report.scenarios:
        status = "PASS" if scenario.passed else f"FAIL [{scenario.severity}]"
        print(f"  [{label}] {status}  {scenario.scenario_id}  {scenario.title}")
        for failure in scenario.failed_assertions:
            print(f"          - {failure.type}/{failure.name}: {failure.detail}")
    print(
        f"  [{label}] {report.suite}: {summary.passed}/{summary.total} passed | "
        f"failed_high={summary.failed_high} failed_medium={summary.failed_medium}"
    )


def _run_suite_over_gateway(
    *, suite: str, eval_dir: Any, harness: ScriptedGatewayHarness
):
    """Run the suite's GATEWAY scenarios through the harness and build the eval report.

    Mirrors :func:`eval_runner.run.run_suite` but filters to :func:`is_gateway_scenario`
    (copilot scenarios are not gateway turns) and reuses the same assertion package +
    report builder unchanged.
    """
    scenarios = [s for s in load_suite(suite, eval_dir) if is_gateway_scenario(s)]
    outcomes = [
        ScenarioOutcome(
            scenario_id=s.scenario_id,
            title=s.title,
            severity=s.assertions.max_severity,
            outcomes=evaluate_scenario(s, harness.run_turn(s)),
        )
        for s in scenarios
    ]
    return build_report(suite, outcomes), len(scenarios)


def main(argv: Sequence[str]) -> int:
    args = _parse_args(list(argv))
    harness = ScriptedGatewayHarness(
        gateway_url=args["gateway_url"],
        webhook_token=args["webhook_token"],
        transcripts_dir=args["transcripts_dir"],
        record_dir=args["record_dir"],
        poll_timeout=args["poll_timeout"],
    )

    signatures = []
    reports = []
    for run_index in range(args["runs"]):
        label = f"run {run_index + 1}/{args['runs']}"
        print(f"[harness] {label}: driving suite '{args['suite']}' gateway scenarios...")
        report, n = _run_suite_over_gateway(
            suite=args["suite"], eval_dir=args["eval_dir"], harness=harness
        )
        print(f"  [{label}] {n} gateway scenario(s) selected from '{args['suite']}'")
        _print_report(label, report)
        signatures.append(_assertion_signature(report))
        reports.append(report)

    # Determinism (NFR-6): every run's assertion outcomes must be byte-identical.
    first = json.dumps(signatures[0], sort_keys=True)
    for i, sig in enumerate(signatures[1:], start=2):
        if json.dumps(sig, sort_keys=True) != first:
            print(f"[harness] DETERMINISM FAIL: run 1 and run {i} differ on assertions.")
            return 1
    print(f"[harness] determinism OK: {args['runs']} runs byte-stable on the assertions.")

    # Go-live gate (parity with eval_runner.cli): high-severity failures block.
    failed_high = max(r.summary.failed_high for r in reports)
    if failed_high > 0:
        print(f"[harness] GATE FAIL: {failed_high} high-severity scenario(s) failed.")
        return 1
    print("[harness] GATE PASS: no high-severity failures, deterministic across runs.")
    return 0


def _parse_args(argv: list[str]) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "suite": "text_first_launch",
        "gateway_url": _DEFAULT_GATEWAY_URL,
        "webhook_token": _DEFAULT_WEBHOOK_TOKEN,
        "eval_dir": _DEFAULT_EVAL_DIR,
        "transcripts_dir": _DEFAULT_EVAL_DIR / "transcripts",
        "record_dir": None,
        "runs": 2,
        "poll_timeout": _DEFAULT_POLL_TIMEOUT,
    }
    i = 0
    while i < len(argv):
        arg, nxt = argv[i], (argv[i + 1] if i + 1 < len(argv) else None)
        if arg == "--suite":
            opts["suite"] = _require(arg, nxt)
        elif arg == "--gateway-url":
            opts["gateway_url"] = _require(arg, nxt)
        elif arg == "--token":
            opts["webhook_token"] = _require(arg, nxt)
        elif arg == "--eval-dir":
            opts["eval_dir"] = Path(_require(arg, nxt))
        elif arg == "--transcripts-dir":
            opts["transcripts_dir"] = Path(_require(arg, nxt))
        elif arg == "--record-dir":
            opts["record_dir"] = Path(_require(arg, nxt))
        elif arg == "--runs":
            opts["runs"] = int(_require(arg, nxt))
        elif arg == "--poll-timeout":
            opts["poll_timeout"] = float(_require(arg, nxt))
        else:
            raise ValueError(f'Unknown argument "{arg}".')
        i += 2
    return opts


def _require(flag: str, value: Optional[str]) -> str:
    if value is None:
        raise ValueError(f"{flag} requires a value.")
    return value


if __name__ == "__main__":  # pragma: no cover - CLI shell
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (HarnessError, ValueError) as err:
        print(f"[harness] FAILED: {err}", file=sys.stderr)
        raise SystemExit(1)

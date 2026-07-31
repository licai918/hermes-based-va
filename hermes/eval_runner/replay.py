"""Replay agent harness: run a recorded Hermes transcript deterministically.

This is the CI half of the record/replay strategy. A live turn (recorded once,
possibly against a real model) is saved as a transcript; CI replays it through
the same transcript parser the live turn uses, so the go-live gate exercises a
real agent's captured behavior with no model, network, or credentials.

**The coverage boundary, stated (0.0.5 S31).** Replay verifies the RECORDING, not
the current model. Every assertion in the replay suite answers "does this
transcript still satisfy this assertion" — a question about a file — so
behavioural drift between the recording and the model running in production is
structurally invisible here, by construction and not by oversight (the
determinism is deliberate and load-bearing, NFR-4). This has already bitten once:
the 0.0.4 quality-feedback acceptance run found the live agent failing
``case_created`` twice out of two while this gate passed in 15 seconds on the same
assertion.

So: **a green launch gate never means "the agent still does X".** It means the
recordings still do. The only live read of the AGENT's current behaviour is the
escalation probe (``hermes_runtime.escalation_check``), which runs OUTSIDE this
gate on the non-blocking advisory CI job; it reports and never gates. Any prose or
panel copy that quotes a green eval gate as evidence about the live agent is
overclaiming.

(Deliberately named without reference to the advisory model-scored machinery:
``tests/test_eval_advisory.py`` forbids every module reachable from
``--harness replay`` from so much as mentioning it, in a comment included, so that
no wording here can ever paper over a real wiring. That guard fired on an earlier
draft of this very paragraph and it was right to.)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Union

from .harness import AgentTurnResult
from .turn_result import build_scenario_turn_result
from .types import MergedScenario

PathLike = Union[str, os.PathLike[str]]


def transcript_path(transcripts_dir: PathLike, scenario: MergedScenario) -> Path:
    """The on-disk transcript location for a scenario: ``<dir>/<suite>/<id>.json``.

    Shared by the recorder (write) and the replay harness (read) so the layout has
    a single source of truth.
    """
    return Path(transcripts_dir) / scenario.suite / f"{scenario.scenario_id}.json"


class TranscriptNotFound(FileNotFoundError):
    """Raised when no recorded transcript exists for a scenario in replay mode."""


class ReplayAgentHarness:
    """An ``AgentHarness`` that replays recorded transcripts.

    Transcripts live at ``<transcripts_dir>/<suite>/<scenario_id>.json`` as
    ``{"final_response": str, "messages": [...]}`` and parse into the same
    :class:`AgentTurnResult` a live turn would produce.
    """

    def __init__(self, transcripts_dir: PathLike) -> None:
        self.transcripts_dir = Path(transcripts_dir)

    def transcript_path(self, scenario: MergedScenario) -> Path:
        return transcript_path(self.transcripts_dir, scenario)

    def run_turn(self, scenario: MergedScenario) -> AgentTurnResult:
        path = self.transcript_path(scenario)
        if not path.is_file():
            raise TranscriptNotFound(
                f"No recorded transcript for scenario '{scenario.scenario_id}' "
                f"(suite '{scenario.suite}') at {path}."
            )
        doc = json.loads(path.read_text(encoding="utf-8"))
        # The transcript composer is channel-agnostic; the scenario-aware builder
        # layers on structural disclosures (ADR-0056), the safety invariants, and the
        # injected-preference signal — the same composition the live recorder uses.
        return build_scenario_turn_result(
            scenario,
            final_response=doc.get("final_response", "") or "",
            messages=doc.get("messages", []) or [],
        )

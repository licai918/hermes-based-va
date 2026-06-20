"""Replay agent harness: run a recorded Hermes transcript deterministically.

This is the CI half of the record/replay strategy. A live turn (recorded once,
possibly against a real model) is saved as a transcript; CI replays it through
the same transcript parser the live turn uses, so the go-live gate exercises a
real agent's captured behavior with no model, network, or credentials.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Union

from .disclosures import derive_disclosures
from .harness import AgentTurnResult
from .transcript import turn_result_from_transcript
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
        result = turn_result_from_transcript(
            final_response=doc.get("final_response", "") or "",
            messages=doc.get("messages", []) or [],
        )
        # The transcript composer is channel-agnostic; structural disclosures
        # (ADR-0056) come from the scenario. Composer-provided keys take
        # precedence over the structural defaults.
        derived = derive_disclosures(channel=scenario.channel)
        return replace(result, disclosures={**derived, **result.disclosures})

"""Persist a captured Hermes turn as a replayable transcript (record half).

A live turn (``run_agent`` returns ``{final_response, messages}``) is captured
once and written here into the exact ``<dir>/<suite>/<scenario_id>.json`` layout
:class:`eval_runner.replay.ReplayAgentHarness` reads, so CI replays it
deterministically with no model, network, or credentials (ADR-0121).

Booting the real ``AIAgent`` + provider seam is a separate dependency-gated
adapter; this module owns only the persistence contract that adapter must meet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .replay import PathLike, transcript_path
from .types import MergedScenario


def record_turn(
    *, turn: Mapping[str, Any], scenario: MergedScenario, transcripts_dir: PathLike
) -> Path:
    """Write ``turn`` as the recorded transcript for ``scenario``; return its path."""
    path = transcript_path(transcripts_dir, scenario)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "final_response": turn.get("final_response", "") or "",
        "messages": turn.get("messages", []) or [],
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path

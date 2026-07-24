"""Machine-readable gate-report artifacts for the QualityGatesPanel live read (S23, FR-32).

The knowledge gates harness (:mod:`hermes_runtime.knowledge.gates`) and the advisory
judge runnable (:mod:`hermes_runtime.advisory_judge_report`) each print human output
today; this writes the SAME results as a small JSON artifact the workbench admin panel
reads live (newest per kind) so the panel stops hand-copying numbers.

One file per run, timestamped, landing in a reports directory (``GATE_REPORTS_DIR``
env, else ``<repo-root>/.reports/gates``). The workbench reader picks the newest per
kind and renders values + "as of <generated_at>" + provenance (source command / run).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]


def default_reports_dir() -> Path:
    """Where artifacts land: ``GATE_REPORTS_DIR`` env, else ``<repo-root>/.reports/gates``.

    Same default the workbench reader resolves (repo-root ``.reports/gates``), so a run
    with no env set is still visible to the panel without extra wiring.
    """
    env = os.environ.get("GATE_REPORTS_DIR")
    return Path(env) if env else _REPO_ROOT / ".reports" / "gates"


def write_report(
    kind: str,
    source: str,
    rows: Sequence[dict[str, Any]],
    *,
    source_run: Optional[str] = None,
    reports_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Optional[Path]:
    """Write one gate-report artifact; return its path, or None if the write failed.

    ``rows`` are the panel rows verbatim (``name``/``command``/``result``/``passed``/
    ``note``); ``passed=None`` means advisory (no PASS/FAIL), e.g. the judge report.

    BEST-EFFORT: this is a side-report for the admin panel, never part of a gate's
    verdict. An unwritable reports dir (misconfig, read-only CI FS, disk full,
    permission) must NEVER crash or flip the caller's exit code -- especially the
    ADVISORY judge, which never blocks merge (NFR-7). Any OSError is logged and
    swallowed, returning None; callers ignore the return value.
    """
    ts = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    directory = reports_dir or default_reports_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": kind,
            "generated_at": ts.isoformat().replace("+00:00", "Z"),
            "source": source,
            "source_run": source_run or os.environ.get("GATE_REPORT_SOURCE_RUN"),
            "rows": [dict(r) for r in rows],
        }
        stamp = ts.strftime("%Y%m%dT%H%M%S%fZ")
        path = directory / f"{kind}-{stamp}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path
    except OSError as err:
        print(f"warning: could not write gate report artifact ({kind}): {err}", file=sys.stderr)
        return None


def demo() -> None:  # ponytail: one runnable self-check, no framework
    """Self-check: a written artifact round-trips with the expected envelope + rows."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = write_report(
            "recall",
            "python -m hermes_runtime.knowledge.gates recall",
            [{"name": "Recall@3", "command": "cmd", "result": "22/30 = 73%", "passed": False, "note": None}],
            reports_dir=Path(tmp),
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["kind"] == "recall"
        assert data["generated_at"].endswith("Z")
        assert data["rows"][0]["passed"] is False
        assert path.name.startswith("recall-") and path.suffix == ".json"
    print("gate_report_artifact.demo: OK")


if __name__ == "__main__":  # pragma: no cover - thin self-check shell
    demo()

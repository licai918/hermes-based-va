"""``python -m eval_runner`` entry point (ADR-0121)."""

from __future__ import annotations

from .cli import _entrypoint

raise SystemExit(_entrypoint())

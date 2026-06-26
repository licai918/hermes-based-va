"""``pre_llm_call`` context injection (ADR-0140, ADR-0113).

Per-turn, Hermes calls ``pre_llm_call`` and appends any returned ``{"context": ...}``
to the *user* message (never the system prompt, preserving the prefix cache). We
use it to inject the Session Identity Snapshot and a compact Customer Memory
preference block sourced from the Toee Business Datastore (the system of record,
ADR-0140) — not the Hermes built-in memory tool. Providers are injected by the
embedding layer; absent providers make the hook an observer that injects nothing.
A provider error must never break the turn, so failures are swallowed to ``None``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# session_id -> Session Identity Snapshot mapping (or None when unresolved).
SnapshotProvider = Callable[[str], Optional[dict[str, Any]]]
# session_id -> list of Customer Memory preference slots (or None/empty).
MemoryProvider = Callable[[str], Optional[list[dict[str, Any]]]]


def _render_snapshot(snapshot: Optional[dict[str, Any]]) -> Optional[str]:
    if not snapshot:
        return None
    lines = [f"- {key}: {value}" for key, value in snapshot.items()]
    return "Session Identity Snapshot:\n" + "\n".join(lines)


def _render_memory(memory: Optional[list[dict[str, Any]]]) -> Optional[str]:
    if not memory:
        return None
    lines: list[str] = []
    for slot in memory:
        name = slot.get("slot")
        value = slot.get("value")
        if name is None:
            continue
        lines.append(f"- {name}: {value}")
    if not lines:
        return None
    return "Customer Memory (preferences):\n" + "\n".join(lines)


def render_injection(
    snapshot: Optional[dict[str, Any]],
    memory: Optional[list[dict[str, Any]]],
) -> Optional[str]:
    """Render the combined injection block, or ``None`` when there is nothing."""
    parts = [
        part
        for part in (_render_snapshot(snapshot), _render_memory(memory))
        if part
    ]
    if not parts:
        return None
    return "\n\n".join(parts)


def make_pre_llm_call_hook(
    *,
    snapshot_provider: Optional[SnapshotProvider] = None,
    memory_provider: Optional[MemoryProvider] = None,
) -> Callable[..., Optional[dict[str, str]]]:
    """Build the ``pre_llm_call`` callback bound to identity/memory providers."""

    def hook(
        session_id: Optional[str] = None, **kwargs: Any
    ) -> Optional[dict[str, str]]:
        snapshot: Optional[dict[str, Any]] = None
        memory: Optional[list[dict[str, Any]]] = None
        if snapshot_provider is not None and session_id is not None:
            try:
                snapshot = snapshot_provider(session_id)
            except Exception:
                snapshot = None
        if memory_provider is not None and session_id is not None:
            try:
                memory = memory_provider(session_id)
            except Exception:
                memory = None
        text = render_injection(snapshot, memory)
        if not text:
            return None
        return {"context": text}

    return hook

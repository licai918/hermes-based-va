"""Governed ``ToolDriver`` for ``toee_knowledge_search``, backed by the S08
retriever (FR-4, NFR-5, S09).

Routes ``search_public_site`` through :func:`hermes_runtime.knowledge.retriever.retrieve`
under a hard wall-clock deadline: the whole retrieval call (query embedding
inference + SQL) runs in a worker thread, and a timeout or any retriever
exception degrades to the governed no-match shape -- never raises, never
blocks the turn past the budget (NFR-5). ``search_operational_policy`` is out
of scope for this slice (S09) and is delegated unchanged to a held fallback
driver (default: the mock).

Not wired onto any turn profile here (extra_drivers injection into
``openrouter.py``/``copilot_turn.py`` is S10's job) -- this module only
provides the gate + driver the overlay will use.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING, Any, Optional

from toee_hermes.drivers.mock import create_all_mock_handlers
from toee_hermes.drivers.mock.driver import MockDriver

from .retriever import EmbedQueryFn, retrieve

if TYPE_CHECKING:  # pragma: no cover - typing only
    from toee_hermes.execute import ToolRequest
    from toee_hermes.tool_gate import ToolExecutionContext

logger = logging.getLogger(__name__)

# Env var gating L5 Knowledge retrieval. Values: unset/"" -> disabled, "retriever" -> on.
KNOWLEDGE_BACKEND_ENV = "KNOWLEDGE_BACKEND"

# Wall-clock budget (ms) for one retrieval call (query embed + SQL), FR-7b's budget.
KNOWLEDGE_DEADLINE_ENV = "KNOWLEDGE_RETRIEVAL_DEADLINE_MS"
DEFAULT_DEADLINE_MS = 800.0

_UNSET = object()

# Governed no-match shape for search_public_site, matching the mock driver's
# exact contract (drivers/mock/knowledge.py's `_search_public_site`: a
# `results` list, no top-level `found` key -- an empty list IS the miss).
def _not_found() -> dict[str, Any]:
    """Fresh governed-miss shape per call — a shared constant would leak mutations
    (e.g. a future caller appending to result["results"]) across every miss process-wide."""
    return {"results": []}


def knowledge_enabled(value: object = _UNSET) -> bool:
    """Whether L5 Knowledge retrieval is active for this deployment (FR-4).

    NOT the same axis as :func:`hermes_runtime.tool_backend.memory_enabled`
    (=L4 Customer Memory, gated by ``TOOL_BACKEND=datastore``) and NOT Hermes's
    own ``memory.memory_enabled`` (=agent scratch notes) -- three different
    gates that share overlapping vocabulary (the collision the architecture
    map warns about). This one reads ``KNOWLEDGE_BACKEND`` on its own axis:
    unset/"" is disabled (the existing 2-entry mock stub keeps serving
    ``toee_knowledge_search``); ``"retriever"`` turns on the S08 hybrid
    retriever. Independent of ``TOOL_BACKEND`` -- knowledge can be on/off
    regardless of whether the business datastore is live.
    """
    if value is _UNSET:
        value = os.environ.get(KNOWLEDGE_BACKEND_ENV)
    return value == "retriever"


def warm_knowledge_embedder() -> None:
    """Fire-and-forget background warm of the query embedder (S10 cold-load mitigation).

    Documented S09 gap: with ``KNOWLEDGE_BACKEND=retriever``, the first query in a
    fresh process pays the fastembed model's ~800ms+ load time and reliably misses
    the 800ms retrieval deadline (:data:`DEFAULT_DEADLINE_MS`). Composition roots
    (``gateway_composition.build_gateway_app``, ``tool_dispatch_composition.
    build_tool_dispatch_app``) call this once at boot so the model is already
    loaded before the first real query lands. Runs in a daemon thread and never
    raises into the caller; any failure (missing model files, etc.) is caught and
    logged by TYPE only -- a slow/failed warmup must never block or fail boot.
    No-op when knowledge is disabled. Full caching policy is S12/FR-7b; this is
    just the boot-time nudge.
    """
    if not knowledge_enabled():
        return

    def _warm() -> None:
        try:
            from .retriever import fastembed_query_embedder

            fastembed_query_embedder()("warmup")
        except Exception as exc:
            logger.warning("knowledge embedder warmup failed error_type=%s", type(exc).__name__)

    threading.Thread(target=_warm, daemon=True).start()


def _deadline_ms() -> float:
    raw = os.environ.get(KNOWLEDGE_DEADLINE_ENV, "").strip()
    if not raw:
        return DEFAULT_DEADLINE_MS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_DEADLINE_MS


class KnowledgeDriver:
    """Routes ``toee_knowledge_search`` to the retriever, deadline-bounded.

    ``search_public_site`` -> top-k chunks from :func:`retrieve`, reshaped to
    the mock driver's ``{"results": [...]}`` contract (title/url/snippet),
    each result additionally carrying ``chunk_text``. Any other action
    (``search_operational_policy``) is delegated unchanged to
    ``fallback_driver`` (default: the mock), per S09 scope.

    Deadline: a fresh single-worker :class:`~concurrent.futures.ThreadPoolExecutor`
    per call bounds retrieval to ``deadline_ms`` (env ``KNOWLEDGE_RETRIEVAL_DEADLINE_MS``,
    default 800). On expiry (or any exception from the retriever) this returns
    the governed miss and never raises. The pool is shut down with
    ``wait=False`` so a timed-out call does not itself block on the still-running
    worker thread; that worker is simply abandoned (acceptable for a bounded,
    side-effect-free read at this corpus size -- belt-and-braces would add a
    psycopg ``statement_timeout`` on the retriever's connection to bound the SQL
    side too, left as a follow-up, not required to satisfy this deadline).
    """

    kind = "knowledge"

    def __init__(
        self,
        *,
        embed_query_fn: Optional[EmbedQueryFn] = None,
        fallback_driver: Any = None,
        deadline_ms: Optional[float] = None,
        retrieve_fn: Any = None,
    ) -> None:
        self._embed_query_fn = embed_query_fn
        self._fallback = fallback_driver or MockDriver(create_all_mock_handlers())
        self._deadline_ms = deadline_ms
        self._retrieve = retrieve_fn or retrieve

    def execute(self, request: "ToolRequest", context: "ToolExecutionContext") -> Any:
        if request.action != "search_public_site":
            return self._fallback.execute(request, context)
        return self._search_public_site(request.params)

    def _search_public_site(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query")
        query = query if isinstance(query, str) else ""

        deadline = self._deadline_ms if self._deadline_ms is not None else _deadline_ms()
        # Log length/hash only -- the raw query text must never reach logs (FR-4).
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self._retrieve, query, embed_query_fn=self._embed_query_fn)
            try:
                chunks = future.result(timeout=deadline / 1000)
            except FutureTimeoutError:
                logger.warning(
                    "knowledge_search deadline exceeded (query_hash=%s len=%d deadline_ms=%s)",
                    query_hash,
                    len(query),
                    deadline,
                )
                return _not_found()
            except Exception:
                logger.exception(
                    "knowledge_search retriever error (query_hash=%s len=%d)",
                    query_hash,
                    len(query),
                )
                return _not_found()
        finally:
            pool.shutdown(wait=False)

        if not chunks:
            return _not_found()

        return {
            "results": [
                {
                    "title": chunk.title,
                    "url": chunk.url,
                    "snippet": chunk.chunk_text,
                    "chunk_text": chunk.chunk_text,
                }
                for chunk in chunks
            ]
        }

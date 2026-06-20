"""Local in-process agent-turn dispatcher (ADR-0105 local substrate, ADR-0103).

The production JobQueue is Cloud Tasks: the webhook enqueues a task and Cloud Tasks
POSTs it to the protected internal route, which runs the turn. Locally there is no
task service, so :class:`LocalDispatchingJobQueue` is the dev/test substrate that
runs the *same* shared :func:`execute_agent_turn_job` itself — reload, verify
binding, run — so a locally-booted app actually replies end-to-end.

It preserves fast-ack (ADR-0103): ``enqueue`` is called inside the webhook handler,
so the turn is dispatched out-of-band (default: a daemon thread) and ``enqueue``
returns immediately rather than blocking the webhook on the model call. The dispatch
mechanism is injectable so tests can run synchronously. Reload + binding
verification still run inside the shared job (ADR-0107), exactly as on the HTTP path.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from toee_hermes.gateway.agent_turn import AgentJobPayload

from hermes_runtime.agent_turn_job import execute_agent_turn_job

# Schedules a unit of work to run out-of-band relative to the caller.
DispatchFn = Callable[[Callable[[], None]], None]


def _thread_dispatch(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


class LocalDispatchingJobQueue:
    """In-process JobQueue that drives each enqueued turn out-of-band.

    Holds the same ``store`` and ``turn_runner`` the internal route uses so a
    reloaded turn runs against the persisted context. ``dispatch`` defaults to a
    daemon thread (fast-ack); inject a synchronous dispatch in tests.
    """

    def __init__(
        self,
        *,
        store: Any,
        turn_runner: Any,
        dispatch: DispatchFn = _thread_dispatch,
    ) -> None:
        self._store = store
        self._turn_runner = turn_runner
        self._dispatch = dispatch

    def enqueue(self, payload: AgentJobPayload) -> None:
        self._dispatch(
            lambda: execute_agent_turn_job(
                store=self._store, turn_runner=self._turn_runner, payload=payload
            )
        )

"""A turn's tool fence must be opt-OUT, not opt-in (D27 root cause).

WHY THIS FILE EXISTS. `live.run_agent_turn` admits `governed_tool_names` to the
agent's `valid_tool_names`. With `tools_exclusive=False` it **UNIONs** them into
whatever the SDK agent already carries -- and what it already carries is the
Hermes built-in toolset: `terminal`, `execute_code`, `write_file`, `patch`,
`process`, `delegate_task`, and twenty more (25 in total, verified by probing a
constructed agent).

`live.py`'s own comment states the requirement -- *"Gateway SMS turns must not
inherit Hermes built-ins (terminal, read_file, …)"* -- but expressed it as a
DEFAULT the caller must remember to override. D27 recorded the two capture forks
that forgot. This file is about the class rather than those two instances: with
an opt-in fence, the next caller that forgets inherits a shell.

The default is therefore inverted here: **fencing is what you get; unioning the
built-ins in is what you ask for.** Harness flexibility (eval and scripted runs
that genuinely want the built-ins) is preserved by asking for it explicitly,
which is a visible line a reviewer can see rather than an absence they cannot.
"""

from __future__ import annotations

import os
import tempfile

import pytest

# The SDK built-ins that must never ride along on a turn whose input is
# customer-influenced. Not the whole set -- the ones whose presence would be
# indefensible, so the assertion reads as what it is protecting against.
_INDEFENSIBLE = ("terminal", "execute_code", "write_file", "patch")


@pytest.fixture
def _agent_probe(monkeypatch):
    """Capture the `valid_tool_names` a turn actually hands the loop.

    Drives the real `live.run_agent_turn` seam with a fake AIAgent, so the
    assertion is on the production admission logic rather than on a restatement
    of it. `run_agent` is imported inside the function under test, so the fake is
    installed on the module object the import resolves to.
    """
    os.environ.setdefault("HERMES_HOME", tempfile.mkdtemp(prefix="fence-probe-"))
    import run_agent

    seen: dict[str, set[str]] = {}

    class _FakeAgent:
        def __init__(self, **_kwargs):
            # What a real constructed agent carries before any narrowing. The
            # exact members matter less than that the built-ins are present:
            # this is the set the union would otherwise admit.
            self.valid_tool_names = {"terminal", "execute_code", "write_file", "patch", "read_file"}
            self._disable_streaming = False

        def run_conversation(self, _user_message, system_message=None):
            del system_message
            seen["valid"] = set(self.valid_tool_names or set())
            return {"final_response": "ok", "messages": []}

    monkeypatch.setattr(run_agent, "AIAgent", _FakeAgent)
    return seen


def _run(seen, **kwargs):
    from hermes_runtime.live import run_agent_turn

    run_agent_turn(
        user_message="hi",
        system_message="be helpful",
        base_url="http://example.invalid",
        api_key="k",
        model="m",
        max_iterations=1,
        **kwargs,
    )
    return seen["valid"]


def test_a_narrowed_toolset_does_not_inherit_a_shell_by_default(_agent_probe):
    """The one that reddens today: fencing must not require remembering a flag.

    A caller narrowing to its own governed tools is asking for a fence. Before
    the default was inverted this quietly returned the union, so the caller got
    `terminal` — on a path whose input is customer-authored text.
    """
    admitted = _run(_agent_probe, governed_tool_names=("toee_semantic_lexicon",))

    leaked = sorted(name for name in _INDEFENSIBLE if name in admitted)
    assert not leaked, (
        f"a turn that narrowed its toolset was still handed {leaked}. The fence is "
        "the default; a caller that wants the SDK built-ins must ask for them by "
        "passing tools_exclusive=False, where a reviewer can see the request."
    )
    assert admitted == {"toee_semantic_lexicon"}


def test_the_union_is_still_available_but_has_to_be_asked_for(_agent_probe):
    """Inverting a default must not delete the capability underneath it.

    Eval and scripted harnesses legitimately want the built-ins. That stays
    possible — it just stops being what silence means.
    """
    admitted = _run(
        _agent_probe,
        governed_tool_names=("toee_semantic_lexicon",),
        tools_exclusive=False,
    )

    assert "terminal" in admitted
    assert "toee_semantic_lexicon" in admitted


def test_passing_no_governed_names_still_leaves_the_agent_untouched(_agent_probe):
    """The empty case is not the fenced case, and conflating them would be a bug.

    `governed_tool_names=()` means "this caller is not governing the toolset at
    all" — the pre-existing behaviour, and not something this change should
    silently convert into an empty fence that admits nothing.
    """
    admitted = _run(_agent_probe, governed_tool_names=())

    assert "terminal" in admitted

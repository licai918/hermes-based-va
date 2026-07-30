"""Every fail-closed layer seam must be DECIDED in the deployment, not defaulted.

FOUND BY RUNNING THE S29 OWNER WALKTHROUGH. `injection_ledger` had **zero rows**
after six real customer turns, so blast radius was permanently 0 open cases, so
retiring an entry raised no review item, so PAC-3/PAC-5/PAC-7 had nothing to
demonstrate. Probed inside the running turn-worker:

    ON   L4 customer memory (TOOL_BACKEND)
    ON   L5 knowledge retrieval (KNOWLEDGE_BACKEND)
    OFF  L6 injected into EXTERNAL turn
    OFF  L6 injected into COPILOT draft
    OFF  L7 lexicon injected into EXTERNAL turn
    OFF  L7 lexicon injected into COPILOT draft

L6 and L7 never reached a prompt. 0.0.5's headline layer was inert in the product
while every test that covers it passed, for the same reason D29's L5 was: the flag
is fail-closed by design (correct -- it keeps the eval replay path byte-identical,
NFR-4) and `docker-compose.yml` never turned it on. The whole file mentioned these
flags exactly once, commented out.

**The lesson these tests encode is not "the flag was off".** It is that NOBODY
DECIDED -- the default just happened, invisibly, for two iterations. So the general
guard below does not demand every seam be ON; it demands every seam be *named in
the deployment file*, so that "off" is a recorded choice a reader can disagree with
rather than an omission nobody can see.

DERIVED, NOT LISTED. The seam set comes from `_flag_on`'s call sites -- the shared
fail-closed helper -- so a seam added next iteration is covered the day it is
added. A hardcoded list would have covered exactly the four flags already known to
be broken, which is the shape of test that never finds the fifth one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from hermes_runtime import latency as latency_module  # noqa: E402
from hermes_runtime import tool_backend  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker-compose.yml"

# Modules that gate a capability behind `_flag_on`. Scanned rather than imported
# wholesale so an unrelated `*_ENV` constant (a tuning knob like the retrieval
# deadline, which has a sane default and is NOT a capability gate) cannot drift
# into the set and turn this into a test nobody can keep green.
_FLAG_MODULES = (tool_backend, latency_module)
_FLAG_ON_CALL = re.compile(r"_flag_on\(\s*([A-Z][A-Z0-9_]*)\b")

# The seams 0.0.5's acceptance depends on. L6/L7 must reach a prompt or PAC-1
# (a seasonal default the agent acts on), PAC-3 and PAC-5 and PAC-7 (all of which
# read `injection_ledger`, which only fills when something is injected) have
# nothing to demonstrate.
_REQUIRED_ON = {
    "LEXICON_EXTERNAL_INJECTION": "L7 glossary into a customer turn (FR-6/FR-7, PAC-1)",
    "LEXICON_INJECTION": "L7 glossary into a copilot draft (FR-6)",
    "AGENT_EXPERIENCE_EXTERNAL_INJECTION": "L6 learnings into a customer turn (FR-25)",
    "AGENT_EXPERIENCE_INJECTION": "L6 learnings into a copilot draft (FR-25)",
}


def _fail_closed_flag_env_vars() -> dict[str, str]:
    """{env var name -> the constant it came from}, derived from `_flag_on` call sites."""
    found: dict[str, str] = {}
    for module in _FLAG_MODULES:
        source = Path(module.__file__).read_text(encoding="utf-8")
        for const in _FLAG_ON_CALL.findall(source):
            value = getattr(module, const, None)
            if isinstance(value, str) and value:
                found[value] = const
    return found


def _compose_text() -> str:
    return _COMPOSE.read_text(encoding="utf-8")


def _compose_env() -> dict[str, object]:
    """Every environment key compose SETS (anchors resolved), across all services."""
    compose = yaml.safe_load(_compose_text())
    merged: dict[str, object] = {}
    for spec in (compose.get("services") or {}).values():
        env = (spec or {}).get("environment") or {}
        if isinstance(env, dict):
            merged.update(env)
    return merged


def test_the_derivation_itself_found_flags():
    """Guard the guard: renaming `_flag_on` must not silently empty this suite.

    Without it, the parametrized tests below would run over zero cases and report
    PASS -- the exact failure mode this iteration kept finding in its own tests.
    """
    found = _fail_closed_flag_env_vars()
    assert len(found) >= 5, (
        f"only {len(found)} fail-closed flags derived from _flag_on call sites "
        f"({sorted(found)}). The scan is broken, so every assertion below is "
        "vacuous rather than satisfied."
    )


@pytest.mark.parametrize("env_var", sorted(_fail_closed_flag_env_vars()))
def test_every_fail_closed_seam_is_named_in_the_deployment(env_var):
    """A seam that is OFF must be off ON PURPOSE, and visibly.

    Not "must be on" -- some of these are genuine policy choices (whether a fork
    may propose, whether a read budget is enforced). The requirement is that the
    deployment file MENTIONS it, so a reader can see the decision and argue with
    it. What went wrong was never a wrong value; it was an absent one.

    A commented-out line satisfies this deliberately: it is a recorded decision.
    """
    text = _compose_text()

    assert env_var in text, (
        f"{env_var} gates a memory-layer capability and is fail-closed (unset = OFF), "
        f"but docker-compose.yml never mentions it. The layer is then silently inert "
        f"on every deployment built from this file -- which is how L6 and L7 shipped "
        f"unreachable for two iterations while their tests passed. Set it, or write it "
        f"as a commented line saying why it stays off."
    )


@pytest.mark.parametrize("env_var,why", sorted(_REQUIRED_ON.items()))
def test_the_seams_0_0_5_acceptance_depends_on_are_actually_on(env_var, why):
    """The four that must be ON, because a PAC cannot be demonstrated without them.

    `injection_ledger` only gets a row when something was injected. Empty ledger ->
    blast radius sees 0 open cases -> `measure_and_emit` returns None by design
    ("0 open cases touched by retired entry X -- review?" is noise) -> the inbox
    stays empty forever -> PAC-3, PAC-5 and PAC-7 are undemonstrable. PAC-1 needs
    the seasonal `default_rule` to reach the prompt at all.
    """
    value = _compose_env().get(env_var)

    assert value is not None, f"compose does not set {env_var} -- needed for {why}"
    assert str(value).strip().lower() in {"on", "true", "1", "yes"}, (
        f"compose sets {env_var}={value!r}, which `_flag_on` reads as OFF. "
        f"Needed for {why}."
    )

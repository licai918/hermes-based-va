"""The TypeScript tool catalog must mirror the Python one, exactly.

WHY THIS FILE EXISTS. The catalog lives in two places -- ``toee_hermes.tool_catalog``
and ``packages/shared/src/tools.ts`` -- and they silently diverged by five whole
tools and six actions before anyone noticed. Nothing caught it because the test
that looked like it would (``tools.test.ts``, "contains exactly the 18 v1 tool
names") compared ``TOOL_NAMES`` against a **hardcoded array literal**. It fires
only when someone edits ``tools.ts`` without editing the test; it cannot see the
Python catalog at all, so a Python-side addition was invisible to it by
construction. A hardcoded restatement of the value under test is not a drift
test -- it is the value under test, written twice.

WHY IT LIVES HERE. CI runs the TypeScript and Python suites as separate jobs, and
Python can read a ``.ts`` file far more easily than vitest can run Python. A
generated JSON artifact committed to the repo would work too, but it would need
regenerating -- i.e. it would be a third copy and a third thing to drift. Reading
the source of truth directly means there is nothing to keep in sync.

NO EXCLUSION LIST, DELIBERATELY. The obvious alternative -- allow the TypeScript
side to omit tools, with an exclusion list naming each one -- was rejected. The
0.0.5 iteration learned the same lesson three separate times: **a registry you
must remember to add to is a place for omissions to hide.** An exclusion list is
opt-in by construction, so the next tool nobody registers is invisible exactly
the way these five were. Equality has no such hiding place. If a genuine reason
to exclude something ever appears, adding the mechanism then is a deliberate act
with a reviewer attached; adding it now would pre-build the hiding place.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from toee_hermes.tool_catalog import TOOL_CATALOG

_TS_CATALOG = (
    Path(__file__).resolve().parents[2] / "packages" / "shared" / "src" / "tools.ts"
)

# The object literal we care about, up to the `as const` that closes it.
_BLOCK_RE = re.compile(
    r"export const TOOL_CATALOG\s*=\s*\{(?P<body>.*?)\}\s*as const", re.DOTALL
)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_ENTRY_RE = re.compile(r"(?P<tool>toee_[A-Za-z0-9_]+)\s*:\s*\[(?P<actions>[^\]]*)\]")
_STRING_RE = re.compile(r'"([^"]*)"')


def _parse_typescript_catalog(source: str) -> dict[str, list[str]]:
    """Extract ``{tool: [actions]}`` from the TypeScript source.

    Raises rather than returning something empty-but-plausible: a parse that
    quietly yields ``{}`` would make this test report "the TypeScript side has no
    tools", which is a confusing way to say "I could not read the file". The
    equality assertion below would still go red -- but the failure should name its
    real cause.
    """
    block = _BLOCK_RE.search(source)
    if block is None:
        raise AssertionError(
            f"Could not find the TOOL_CATALOG object literal in {_TS_CATALOG}. "
            "If the file was restructured, update the parser in this test -- do "
            "NOT relax the assertion."
        )
    body = _LINE_COMMENT_RE.sub("", block.group("body"))
    parsed = {
        entry.group("tool"): _STRING_RE.findall(entry.group("actions"))
        for entry in _ENTRY_RE.finditer(body)
    }
    if not parsed:
        raise AssertionError(
            f"Parsed zero tools out of {_TS_CATALOG}. The object literal was "
            "found but no `toee_*: [...]` entries matched, so the parser is "
            "broken rather than the catalog being empty."
        )
    return parsed


@pytest.fixture(scope="module")
def typescript_catalog() -> dict[str, list[str]]:
    if not _TS_CATALOG.exists():
        # Deliberately a failure, not a skip. A skip here is exactly how the
        # original divergence stayed invisible for two iterations.
        raise AssertionError(f"{_TS_CATALOG} is missing; cannot check catalog parity.")
    return _parse_typescript_catalog(_TS_CATALOG.read_text(encoding="utf-8"))


def test_both_catalogs_declare_the_same_tools(
    typescript_catalog: dict[str, list[str]],
) -> None:
    python_tools = set(TOOL_CATALOG)
    ts_tools = set(typescript_catalog)

    assert ts_tools == python_tools, (
        "The TypeScript and Python tool catalogs disagree.\n"
        f"  Only in Python ({len(python_tools - ts_tools)}): "
        f"{sorted(python_tools - ts_tools)}\n"
        f"  Only in TypeScript ({len(ts_tools - python_tools)}): "
        f"{sorted(ts_tools - python_tools)}\n"
        "packages/shared/src/tools.ts mirrors toee_hermes.tool_catalog exactly. "
        "Add the tool to both, or remove it from both."
    )


def test_both_catalogs_declare_the_same_actions_per_tool(
    typescript_catalog: dict[str, list[str]],
) -> None:
    """Compared as SETS, not sequences.

    Order is a formatting concern -- the two files are written by different
    people in different languages and a reordering is not a defect. What matters
    is that the same actions exist on both sides. The per-tool ``toEqual``
    assertions in ``tools.test.ts`` pin exact ordering on the TypeScript side
    where anyone actually depends on it.
    """
    drift: list[str] = []
    for tool in sorted(set(TOOL_CATALOG) & set(typescript_catalog)):
        python_actions = set(TOOL_CATALOG[tool])
        ts_actions = set(typescript_catalog[tool])
        if python_actions != ts_actions:
            drift.append(
                f"  {tool}:\n"
                f"    only in Python:     {sorted(python_actions - ts_actions)}\n"
                f"    only in TypeScript: {sorted(ts_actions - python_actions)}"
            )

    assert not drift, (
        "The TypeScript and Python catalogs agree on tool names but disagree on "
        "actions:\n" + "\n".join(drift)
    )


def test_the_typescript_catalog_has_no_duplicate_actions(
    typescript_catalog: dict[str, list[str]],
) -> None:
    """A duplicate would make the set comparison above pass while the array lies.

    Without this, ``["a", "a"]`` and ``["a"]`` compare equal as sets, so a
    copy-paste slip in the TypeScript array would survive the parity check.
    """
    duplicated = {
        tool: actions
        for tool, actions in typescript_catalog.items()
        if len(actions) != len(set(actions))
    }
    assert not duplicated, f"Duplicate actions in tools.ts: {duplicated}"

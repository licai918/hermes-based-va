"""L5 retrieval must be WIRED where turns actually run, not just implemented.

FOUND BY ASKING THE PRODUCT A REAL QUESTION. During the 0.0.5 S24 layer-② walkthrough
the simulator was asked "i need to return some tires" and the agent replied *"I don't
have our return policy on hand to share here"* -- while FR-30's gate scored that same
question a HIT on `return-policy` + `REFUND_POLICY`.

The gate and the product were measuring different seams:

  * the gate calls :func:`hermes_runtime.knowledge.retriever.retrieve` directly, on a
    HOST venv where fastembed happens to be installed (from the 0.0.3 spike);
  * the agent calls the ``toee_knowledge_search`` TOOL, which only reaches the
    retriever when :func:`~hermes_runtime.knowledge.driver.knowledge_enabled` is true.

`KNOWLEDGE_BACKEND` was never set in docker-compose.yml, so `_knowledge_extra_drivers()`
returned ``None`` and the tool stayed on the mock driver's **two-entry stub**. Probed
inside the running turn-worker: `live driver class = MockDriver`, result `{'results': []}`
-- 15 characters, exactly what the worker log printed for every customer question.

And the switch alone was not enough: `fastembed` was deliberately UNDECLARED
(pyproject's own comment said so, to spare CI a ~100MB model pull), so flipping the
switch produced a retriever that raised on import -> `KnowledgeDriver` caught it ->
the same governed miss, with only a `logger.exception` as evidence. A CI-cost decision
had silently become a product-capability decision.

These tests pin the DEPLOYMENT, because that is the layer that was wrong. The retrieval
logic itself was always correct -- proven in the same probe: once the model was present,
`retrieve()` returned `return-policy` and `REFUND_POLICY` from inside the container.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_PYPROJECT = _REPO_ROOT / "hermes-runtime" / "pyproject.toml"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The value `knowledge_enabled()` accepts. Anything else -- including "true" or "1" --
# leaves the tool on the stub, which is why this asserts the exact token.
RETRIEVER = "retriever"


def _services_on_the_business_path() -> dict[str, dict]:
    """Every compose service wired to the business datastore, DERIVED not listed.

    `TOOL_BACKEND: datastore` marks a service that serves real customer work. Deriving
    the set means a service added later is covered the day it is added; a hardcoded
    list would quietly stop covering the thing it was written for.
    """
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    found = {}
    for name, spec in (compose.get("services") or {}).items():
        env = (spec or {}).get("environment") or {}
        if isinstance(env, dict) and env.get("TOOL_BACKEND") == "datastore":
            found[name] = env
    return found


def test_the_derivation_itself_found_services():
    """Guard the guard: a compose refactor that breaks the query must not read as PASS.

    Without this, renaming `TOOL_BACKEND` would leave every test below parametrized
    over nothing and silently green -- the failure mode this iteration kept hitting.
    """
    assert _services_on_the_business_path(), (
        "no compose service declares TOOL_BACKEND=datastore -- the derivation is "
        "broken, so the assertions below are vacuous rather than satisfied"
    )


@pytest.mark.parametrize("service", sorted(_services_on_the_business_path()))
def test_every_business_path_service_enables_the_retriever(service):
    """The one that was red: compose never set KNOWLEDGE_BACKEND at all.

    A service that serves customer turns without this reaches `toee_knowledge_search`
    through the mock's two-entry stub and tells customers it has no answer -- while
    the corpus sits populated in the database beside it.
    """
    env = _services_on_the_business_path()[service]

    assert env.get("KNOWLEDGE_BACKEND") == RETRIEVER, (
        f"compose service {service!r} runs on the business datastore but does not set "
        f"KNOWLEDGE_BACKEND={RETRIEVER!r}. knowledge_enabled() will be False, the "
        f"knowledge tool stays on the mock's 2-entry stub, and every customer "
        f"knowledge question gets the governed miss. Got: {env.get('KNOWLEDGE_BACKEND')!r}"
    )


def test_the_knowledge_database_is_wired_wherever_the_switch_is():
    """The switch and the DSN must travel together.

    `KNOWLEDGE_BACKEND=retriever` without `KNOWLEDGE_DATABASE_URL` resolves the
    localhost default, which inside a container is not the compose Postgres -- the
    hazard compose's own comment on that variable already describes. Turning the
    switch on is what makes that comment load-bearing.
    """
    for service, env in _services_on_the_business_path().items():
        if env.get("KNOWLEDGE_BACKEND") == RETRIEVER:
            assert env.get("KNOWLEDGE_DATABASE_URL"), (
                f"{service!r} enables the retriever without KNOWLEDGE_DATABASE_URL"
            )


def test_fastembed_is_a_declared_runtime_dependency():
    """The second cause, and the one that would have made a switch-only fix look fine.

    `fastembed` is lazy-imported inside `fastembed_query_embedder`, so an image without
    it does not fail at boot or at import -- it fails on the first customer question,
    inside the try/except that returns the governed miss. Same empty result, same 15
    characters, no traceback the customer or the console ever sees.
    """
    # PARSED, not grepped. The first draft of this test substring-matched the file
    # and PASSED while fastembed was still undeclared -- pyproject's own comment
    # quotes `pytest.skip("fastembed not installed")`, so the assertion was reading
    # prose ABOUT the dependency as evidence OF it. Exactly the defect this whole
    # investigation is about, reproduced inside its own regression test.
    import tomllib

    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    names = {req.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip() for req in declared}

    assert "fastembed" in names, (
        "fastembed is not in hermes-runtime's [project] dependencies (declared: "
        f"{sorted(names)}). The runtime image then cannot embed a query, so L5 "
        "retrieval returns the governed miss on every turn -- silently, because the "
        "import is lazy and the failure is caught."
    )


def test_the_ci_skip_gate_no_longer_exempts_a_missing_embedder():
    """The gate that was carved out around the bug.

    NFR-7's no-silent-skip check failed the job on any skipped live-Postgres test --
    except one whitelisted message, `fastembed not installed`. That carve-out is why
    CI stayed green for two iterations while the embedder path was never executed.
    With fastembed declared the skip cannot occur, so the exemption is not merely
    unnecessary: leaving it in would re-arm the same blind spot the moment someone
    drops the dependency again.
    """
    # Asserts on the MECHANISM, not the vocabulary. The first version of this test
    # searched the whole file for the phrase "fastembed not installed" -- and then
    # went red the moment a COMMENT explained the history, which is prose, not a
    # whitelist. That is the mirror image of the bug this file's sibling test had
    # (matching prose and passing for the wrong reason); the shared root is
    # substring-matching a file instead of asserting on its structure. What must
    # never come back is a `grep -v` filtering the skip check, so that is what is
    # asserted -- the exemption itself, in any wording.
    skip_check = [
        line
        for line in _CI.read_text(encoding="utf-8").splitlines()
        if "^SKIPPED" in line or ("grep" in line and "pytest-runtime.log" in line)
    ]

    assert skip_check, "the NFR-7 no-silent-skip check is gone from ci.yml entirely"
    assert not any("grep -v" in line for line in skip_check), (
        f"ci.yml's no-silent-skip gate has an exemption again: {skip_check}. The "
        "live-embedder tests are the only CI coverage of the retrieval path; "
        "exempting their skip lets the whole path rot behind a green badge."
    )

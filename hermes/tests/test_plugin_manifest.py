"""P5 plugin manifest test: ``plugin.yaml`` must stay in sync with the catalog.

Hermes reads ``plugin.yaml`` (``provides_tools`` / ``provides_hooks``) to render
the plugin banner and discovery logs. ``register()`` filters by profile at load
time, but the static manifest declares the full superset the plugin can provide,
so it must equal every catalog action tool plus the single ``pre_llm_call`` hook.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from toee_hermes.plugin.schemas import build_tool_schemas

MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "toee_hermes" / "plugin" / "plugin.yaml"
)


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_has_identity_fields() -> None:
    data = _manifest()
    assert data["name"]
    assert data["version"]
    assert data["description"]


def test_manifest_declares_pre_llm_call_hook() -> None:
    assert _manifest()["provides_hooks"] == ["pre_llm_call"]


def test_manifest_provides_every_catalog_action_tool() -> None:
    expected = sorted(entry["schema"]["name"] for entry in build_tool_schemas())
    assert sorted(_manifest()["provides_tools"]) == expected

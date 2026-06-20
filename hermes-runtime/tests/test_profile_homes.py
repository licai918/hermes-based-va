"""All three profiles load natively, each home exposing only its toolset.

Production runs one Hermes process per profile (its own ``HERMES_HOME``), so each
profile is verified in an isolated subprocess: a fresh interpreter scaffolds the
profile's home, lets Hermes' own ``discover_plugins()`` find the ``toee``
entry-point plugin, and reports the registered toolsets. This proves per-profile
default-deny (ADR-0034/35/38) end-to-end through the native loader — a property a
shared in-process registry can't show because its global state accumulates across
profiles.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from toee_hermes.plugin.profiles import PROFILE_TOOL_ALLOWLIST, PROFILES

_RUNTIME_ROOT = Path(__file__).resolve().parents[1]

# Every toolset that appears in any profile — used to derive each profile's
# default-deny set (toolsets exclusive to the other profiles).
_ALL_TOOLSETS: frozenset[str] = frozenset().union(*PROFILE_TOOL_ALLOWLIST.values())

_PROBE = r"""
import json, os, sys, tempfile
from hermes_runtime.home import write_profile_home

profile = sys.argv[1]
home = write_profile_home(profile=profile, home=tempfile.mkdtemp(prefix="hh-"))
for key, value in home.env.items():
    os.environ[key] = value
os.environ.pop("HERMES_ENABLE_PROJECT_PLUGINS", None)

from hermes_cli.plugins import discover_plugins, get_plugin_manager, has_hook
from tools.registry import registry

discover_plugins(force=True)
loaded = get_plugin_manager()._plugins.get("toee")
print("PROBE_JSON=" + json.dumps({
    "loaded": bool(loaded and loaded.enabled and not loaded.error),
    "toolsets": registry.get_registered_toolset_names(),
    "has_pre_llm_hook": has_hook("pre_llm_call"),
}))
"""


def _run_profile_probe(profile: str) -> dict:
    """Boot ``profile`` in a fresh interpreter and return its native-load report."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_RUNTIME_ROOT) + (os.pathsep + existing if existing else "")
    )
    # Start clean so the probe's own per-profile home is the only selector.
    for key in ("HERMES_HOME", "TOEE_HERMES_PROFILE", "HERMES_ENABLE_PROJECT_PLUGINS"):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, profile],
        cwd=str(_RUNTIME_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"probe failed:\nSTDOUT{result.stdout}\nSTDERR{result.stderr}"
    line = next(
        ln for ln in result.stdout.splitlines() if ln.startswith("PROBE_JSON=")
    )
    return json.loads(line[len("PROBE_JSON=") :])


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_home_loads_only_its_toolset_natively(profile: str) -> None:
    report = _run_profile_probe(profile)
    registered = set(report["toolsets"])

    assert report["loaded"], f"{profile} home did not natively load the toee plugin"

    allowed = set(PROFILE_TOOL_ALLOWLIST[profile])
    missing = allowed - registered
    assert not missing, f"{profile} did not register allowlisted toolsets: {missing}"

    forbidden = (_ALL_TOOLSETS - allowed) & registered
    assert not forbidden, f"{profile} leaked other profiles' toolsets: {forbidden}"

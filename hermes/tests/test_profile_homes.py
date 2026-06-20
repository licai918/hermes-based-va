"""P5 profile home scaffolds: one Hermes HERMES_HOME per profile (ADR-0139).

Each profile is a Hermes home dir with ``config.yaml`` (enables the ``toee-tire``
plugin), ``SOUL.md`` (the profile's response policy, loaded from HERMES_HOME by
the agent), and ``.env.example`` (selects the profile via ``TOEE_HERMES_PROFILE``,
which the plugin's :func:`resolve_profile` reads to apply the right allowlist).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toee_hermes.plugin.profiles import PROFILES

HOMES = Path(__file__).resolve().parents[1] / "profiles"


def test_profile_homes_match_known_profiles() -> None:
    dirs = {child.name for child in HOMES.iterdir() if child.is_dir()}
    assert dirs == set(PROFILES)


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_home_has_required_files(profile: str) -> None:
    home = HOMES / profile
    assert (home / "config.yaml").is_file()
    assert (home / "SOUL.md").read_text(encoding="utf-8").strip()
    env = (home / ".env.example").read_text(encoding="utf-8")
    assert f"TOEE_HERMES_PROFILE={profile}" in env


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_config_enables_toee_plugin(profile: str) -> None:
    cfg = yaml.safe_load((HOMES / profile / "config.yaml").read_text(encoding="utf-8"))
    assert "toee-tire" in cfg["plugins"]["enabled"]

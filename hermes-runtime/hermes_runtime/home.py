"""Per-profile HERMES_HOME scaffolding for native plugin discovery (ADR-0139).

Each Toee profile runs as its own Hermes profile in a separate ``HERMES_HOME``
(separate session/memory/state). A home enables the ``toee`` entry-point plugin
via ``config.yaml`` (``plugins.enabled: [toee]``); the active profile is selected
at boot by the ``TOEE_HERMES_PROFILE`` process env var (``.env`` only reloads
Hermes-known keys, so the selector must be a real env var, not baked into config).

:func:`write_profile_home` writes that home and returns the exact environment the
launcher/runtime must apply, so the profile selection is functional without this
helper mutating global process state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from toee_hermes.plugin.profiles import PROFILE_ENV_VAR, PROFILES

# Entry-point name under ``[project.entry-points."hermes_agent.plugins"]`` in
# hermes/pyproject.toml; also the key Hermes' ``plugins.enabled`` allow-list matches.
TOEE_PLUGIN_KEY = "toee"


@dataclass(frozen=True)
class ProfileHome:
    """A scaffolded Hermes home plus the env a launcher must apply to use it."""

    home: Path
    env: dict[str, str]


def write_profile_home(*, profile: str, home: str | Path) -> ProfileHome:
    """Scaffold ``home`` as a Hermes home that natively loads the ``toee`` plugin.

    Validates ``profile`` against the authoritative allowlist (fail-closed: an
    unknown profile raises rather than scaffolding a home that would resolve to
    the wrong toolset), writes ``config.yaml`` enabling the ``toee`` plugin, and
    returns the home with the ``{HERMES_HOME, TOEE_HERMES_PROFILE}`` env to apply.
    """
    if profile not in PROFILES:
        raise ValueError(
            f'Unknown profile "{profile}". Expected one of: {", ".join(PROFILES)}.'
        )

    home_path = Path(home)
    home_path.mkdir(parents=True, exist_ok=True)
    config_path = home_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"plugins": {"enabled": [TOEE_PLUGIN_KEY]}}, sort_keys=False),
        encoding="utf-8",
    )

    return ProfileHome(
        home=home_path,
        env={"HERMES_HOME": str(home_path), PROFILE_ENV_VAR: profile},
    )

"""Concrete Tool Gates that plug into governed dispatch (ADR-0033).

Tool Gates are the policy hook point inside :func:`toee_hermes.execute.execute_tool`;
they are not separate Hermes core modules. Each profile contributes the gate(s)
its policy requires.
"""

from __future__ import annotations

from .external_profile import create_external_profile_gate

__all__ = ["create_external_profile_gate"]

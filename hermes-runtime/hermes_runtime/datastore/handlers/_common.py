"""Shared helpers for the Postgres datastore handlers (Slice 33).

Param reading mirrors the mock drivers (snake_case-first with a camelCase
fallback) so the datastore and mock paths accept identical inputs. Rows are made
JSON-safe before they leave a handler, since the dispatch app JSON-encodes the
result (ADR-0141).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from psycopg.types.json import Jsonb


def new_id(prefix: str) -> str:
    """A unique row id, e.g. ``case_3f1c...``. TEXT keys keep seeding flexible."""
    return f"{prefix}_{uuid.uuid4().hex}"


def read_string(params: dict[str, Any], *keys: str) -> Optional[str]:
    """First non-empty string among ``keys`` (snake_case-first, camelCase fallback)."""
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def serialize_row(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """JSON-safe a ``dict_row``: ``datetime`` columns become ISO-8601 strings."""
    if row is None:
        return None
    return {
        key: (value.isoformat() if isinstance(value, datetime) else value)
        for key, value in row.items()
    }


def insert_audit(
    conn,
    *,
    profile: str,
    account_id: Optional[str],
    action: str,
    target_type: Optional[str],
    target_id: Optional[str],
    details: Optional[dict[str, Any]] = None,
) -> str:
    """Append a Workbench Audit Log row (ADR-0029/0085) in the caller's transaction.

    Governed writes record who did what to which resource; the row carries
    ``created_at`` for the 7-year tool-call audit retention (ADR-0004).
    """
    audit_id = new_id("audit")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO workbench_audit_log
                (id, account_id, profile, action, target_type, target_id, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                audit_id,
                account_id,
                profile,
                action,
                target_type,
                target_id,
                Jsonb(details or {}),
            ),
        )
    return audit_id


# --- Deterministic entity keys -------------------------------------------------
# The gateway store writes these keys and the Workbench read handlers reconstruct
# them from the identity the caller supplies. Any drift between the two sides is
# invisible — the read just returns empty — so both sides MUST call this one
# function rather than re-spelling the format. (A provider rename moved the SMS
# prefix in the store while a handler kept the old literal, and every simulator
# SMS read-back silently went blank; ADR-0153.)

_EMAIL_CHANNELS = frozenset({"email", "simulated_email"})


def customer_thread_id(channel: str, from_identity: str) -> str:
    """CustomerThread key: one per stable channel identity (ADR-0115).

    ``channel`` accepts either vocabulary — the ingress literals
    (``simpletexting_sms``/``simulated_email``) or the persisted ones
    (``sms``/``email``). ``from_identity`` must already be canonical: E.164 for
    SMS, ``canonicalize_email``'d for email.
    """
    prefix = "email" if channel in _EMAIL_CHANNELS else "sms"
    return f"customer_thread:{prefix}:{from_identity}"

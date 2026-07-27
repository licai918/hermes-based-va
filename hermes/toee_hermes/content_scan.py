"""Write-side content scan for every memory layer (0.0.5 S01 -- D2, D19).

TWO named resolvers, not one. 0.0.3 S22 shipped a single
``scan_agent_experience_content`` that hard-rejected instruction-injection AND
PII in one pass. That composite is wrong for two of the three layers that need a
write scan:

* ``_PHONE_RE`` matches ``205 55 16`` -- a tire size, and the flagship seeded L7
  ``surface_form`` of 0.0.5 -- so an unsplit scan ``policy_blocked``s the
  headline demo of the iteration on the seed path, the capture fork, and every
  aggregator emission.
* L4 is the PII layer BY DESIGN (NFR-6: "L4 PII stays bound to its customer
  only"). A legitimate delivery-habit slot reads "leave at back door, call
  604-555-1212"; running the PII leg there rejects correct customer data.

Per-field policy (D2):

===============================  ==================  =========================
Field                            ``scan_injection``  ``scan_pii``
===============================  ==================  =========================
L7 surface_form / canonical_form  hard-reject         not applied
L7 evidence / proposer_context    hard-reject         redact in place
L6 experience content             hard-reject         hard-reject (unchanged)
L4 slot values + evidence         hard-reject         not applied
===============================  ==================  =========================

ONE module, imported by both the mock and the Postgres twins, so the two can
never drift on what counts as a governed rejection (NFR-7, the S15/S21 lesson).
L6's exact 0.0.3 behaviour is preserved by composing both legs per text -- see
``toee_hermes.drivers.mock.agent_experience.scan_agent_experience_content``.
"""

from __future__ import annotations

import re
from typing import Optional

from .errors import ToolDriverError

# ponytail: a heuristic keyword/regex floor, not a semantic classifier -- the
# FIRST of three lines of defense (the review-fork prompt is upstream of it, the
# human confirm gate downstream). Extend the tuples as new adversarial cases get
# diagnosed, the same way plugin/schemas.py's PARAM_SCHEMAS grows.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior)\s+instructions",
        r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior)\s+instructions",
        r"\bsystem\s*:",
        r"\bassistant\s*:",
        r"\byou are now\b",
        r"<\s*/?\s*tool_call",
        r"\bnew\s+instructions\b",
        r"\boverride\s+(your|the)\s+(instructions|system prompt)\b",
    )
)

# D19: the prompt fences ``toee_hermes.plugin.hooks`` wraps untrusted /
# model-originated memory in. A stored value carrying one of these tokens closes
# its own fence early and puts the rest of itself OUTSIDE it, in the same
# unfenced region as the framework-derived Session Identity Snapshot -- a
# STRUCTURAL escape none of the semantic patterns above can see. Kept honest
# against hooks.py by
# tests/test_content_scan.py::test_fence_tags_cover_every_tag_render_injection_emits;
# a new fence (S06's glossary) must be added here in the same change.
FENCE_TAGS: tuple[str, ...] = (
    "untrusted_customer_memory",
    "confirmed_operational_learnings",
)

_FENCE_TOKEN_RE = re.compile(
    r"<\s*/?\s*(?:" + "|".join(FENCE_TAGS) + r")\s*>", re.IGNORECASE
)

# Email / phone / Shopify-customer-id-shaped tokens.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\-\s]{6,14}\d")
_CUSTOMER_ID_RE = re.compile(r"gid://shopify/Customer/\d+|\bcust_[A-Za-z0-9]{4,}\b")

_PII_PATTERNS: tuple[re.Pattern[str], ...] = (_EMAIL_RE, _PHONE_RE, _CUSTOMER_ID_RE)

PII_REDACTION = "[redacted]"

INJECTION_REJECTED_MESSAGE = (
    "memory write rejected: instruction-injection pattern detected in proposed "
    "content (write-side scan)."
)
PII_REJECTED_MESSAGE = (
    "memory write rejected: content must be operational-only, no customer PII "
    "(NFR-3/NFR-6)."
)


def scan_injection(*texts: Optional[str]) -> None:
    """Hard-reject instruction-injection and fence-escape content.

    Applied to EVERY governed memory write, every layer, every field: an
    injection pattern is never legitimate content anywhere. ``None``/empty
    positionals are skipped so callers can pass an optional field straight
    through.
    """
    for text in texts:
        if not text:
            continue
        if _FENCE_TOKEN_RE.search(text) or any(
            pattern.search(text) for pattern in _INJECTION_PATTERNS
        ):
            raise ToolDriverError("policy_blocked", INJECTION_REJECTED_MESSAGE)


def redact_pii(
    text: Optional[str], *, keep: tuple[Optional[str], ...] = ()
) -> tuple[Optional[str], bool]:
    """Return ``(text with every PII span replaced, whether anything changed)``.

    The L7 ``evidence``/``proposer_context`` policy (D2): those fields are
    verbatim customer exchanges and will routinely carry a phone or an email.
    Rejecting the whole entry over one throws away the very governance evidence
    an admin needs in order to decide, so the matched span is replaced in place
    and the caller records that a redaction happened.

    ``keep`` exempts spans that exactly equal a caller-supplied token. L7 passes
    the entry's own ``surface_form``/``canonical_form``: the spaced tire size
    ``205 55 16`` matches ``_PHONE_RE``, so without this the evidence for the
    flagship seeded entry would be redacted down to "customer said [redacted]"
    -- undecidable, which is the exact harm the redact-don't-reject rule exists
    to avoid. The tokens were already injection-scanned as this entry's own
    accepted domain terms.
    """
    if not text:
        return text, False
    kept = {token.strip().casefold() for token in keep if token}

    def _replace(match: re.Match[str]) -> str:
        span = match.group(0)
        return span if span.strip().casefold() in kept else PII_REDACTION

    redacted = text
    for pattern in _PII_PATTERNS:
        redacted = pattern.sub(_replace, redacted)
    return redacted, redacted != text


def scan_pii(*texts: Optional[str]) -> None:
    """Hard-reject customer PII. NOT applied to L4 slots or L7 domain tokens.

    See the module docstring: the phone heuristic cannot distinguish a tire size
    from a phone number, and L4 is the layer PII legitimately lives in.
    """
    for text in texts:
        if redact_pii(text)[1]:
            raise ToolDriverError("policy_blocked", PII_REJECTED_MESSAGE)

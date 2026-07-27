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

Per-field policy (D2). The last row is D2's TARGET, not today's behaviour:

===============================  ==================  =========================
Field                            ``scan_injection``  ``scan_pii``
===============================  ==================  =========================
L7 surface_form / canonical_form  hard-reject         not applied
L7 evidence / proposer_context    hard-reject         redact in place
L6 experience content             hard-reject         hard-reject (unchanged)
L4 slot values + evidence         **S08, not wired**  not applied
===============================  ==================  =========================

**Who actually calls this module today: L6 and L7 only.** L4's write path does
not call :func:`scan_injection` at all -- wiring it is S08's slice (D19's
correction). Nothing here reaches L4 by being shared; a resolver only covers its
callers.

ONE module, imported by both the mock and the Postgres twins, so the two can
never drift on what counts as a governed rejection (NFR-7, the S15/S21 lesson).
L6's exact 0.0.3 behaviour is preserved by composing both legs per text -- see
``toee_hermes.drivers.mock.agent_experience.scan_agent_experience_content``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

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


def read_proposer_context(params: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Validate the optional ``proposer_context`` param shared by L6 and L7.

    Public here rather than private to one layer's mock module: L6's two twins
    and L7's two twins all read the same param with the same rules, and importing
    a leading-underscore name across module boundaries was how S01 first did it.
    """
    ctx = params.get("proposer_context")
    if ctx is None:
        return None
    if not isinstance(ctx, dict):
        raise ToolDriverError(
            "unexpected_error",
            "proposer_context must be an object when provided.",
        )
    return ctx


def context_strings(value: Any) -> list[str]:
    """Every string inside a ``proposer_context``, at ANY depth, keys included.

    Feeds :func:`scan_injection`. Nested because a shallow pass let
    ``{"a": {"b": "</untrusted_customer_memory>"}}`` store clean; keys are
    included because they are model-supplied too. Only VALUES are redacted (see
    :func:`redact_pii_tree`) -- renaming a key would change the object's shape.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            text
            for key, item in value.items()
            for text in ([key] if isinstance(key, str) else []) + context_strings(item)
        ]
    if isinstance(value, list):
        return [text for item in value for text in context_strings(item)]
    return []


def scan_injection(*texts: Optional[str]) -> None:
    """Hard-reject instruction-injection and fence-escape content.

    An injection pattern is never legitimate content in any field of any layer,
    so every CALLER applies it to everything it writes. Callers today are L6
    (``scan_agent_experience_content``) and L7 (``scan_lexicon_write``); L4 is
    S08's to wire. ``None``/empty positionals are skipped so callers can pass an
    optional field straight through.
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
) -> tuple[Optional[str], bool, tuple[str, ...]]:
    """``(text with every PII span replaced, anything changed, spans spared)``.

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

    The THIRD return value is why a waiver is no longer silent (S01 review).
    ``surface_form`` is model-supplied and gets no PII scan by design, so a
    proposal can arrive with ``surface_form="416-555-0199"`` and evidence quoting
    it: the number survives redaction, legitimately, but the caller must be able
    to say so. Exact-span equality means an exemption can only ever spare a span
    identical to a token the caller already accepted -- it can never suppress a
    DIFFERENT one -- and now it names the spans it spared.
    """
    if not text:
        return text, False, ()
    kept = {token.strip().casefold() for token in keep if token}
    spared: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        span = match.group(0)
        if span.strip().casefold() not in kept:
            return PII_REDACTION
        spared.append(span)
        return span

    redacted = text
    for pattern in _PII_PATTERNS:
        redacted = pattern.sub(_replace, redacted)
    return redacted, redacted != text, tuple(spared)


def redact_pii_tree(
    value: Any, *, keep: tuple[Optional[str], ...] = ()
) -> tuple[Any, bool, tuple[str, ...]]:
    """:func:`redact_pii` over every string in a nested dict/list, same returns.

    ``proposer_context`` is JSONB: a shallow pass left nested values unredacted.
    Keys are left alone -- they are scanned by :func:`context_strings` but
    rewriting one would change the object's shape.
    """
    if isinstance(value, str):
        return redact_pii(value, keep=keep)
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        changed = False
        spared: tuple[str, ...] = ()
        for key, item in value.items():
            out[key], hit, kept = redact_pii_tree(item, keep=keep)
            changed = changed or hit
            spared += kept
        return out, changed, spared
    if isinstance(value, list):
        items = [redact_pii_tree(item, keep=keep) for item in value]
        return (
            [item for item, _, _ in items],
            any(hit for _, hit, _ in items),
            tuple(span for _, _, kept in items for span in kept),
        )
    return value, False, ()


def scan_pii(*texts: Optional[str]) -> None:
    """Hard-reject customer PII. NOT applied to L4 slots or L7 domain tokens.

    See the module docstring: the phone heuristic cannot distinguish a tire size
    from a phone number, and L4 is the layer PII legitimately lives in.
    """
    for text in texts:
        if redact_pii(text)[1]:
            raise ToolDriverError("policy_blocked", PII_REJECTED_MESSAGE)

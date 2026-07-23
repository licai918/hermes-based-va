"""Gadget attribution bridge: verified Shopify customer <-> QBO customer (0.0.4 S27).

Live QBO invoices carry ``CustomerRef.value`` — a QuickBooks customer id — and NO
Shopify id. So a verified Shopify customer's invoices cannot be attributed from the
invoice alone (the S27 bug: ``_invoice_owned_by_verified`` compared a
``shopify_customer_id`` field that live invoices never carry, so every verified
customer got ``[]`` — an empty *success* narrated as "you have no invoices",
regardless of their real balance).

The authoritative join lives in the owner's Gadget app ``paymentstatussync``, which
syncs Shopify orders into QBO and persists a ``qboCustomerMapping`` model
(``qboCustomerId`` <-> ``shopifyCustomerGid`` with a review ``status``). This module
reads that model over the Gadget API and exposes the single attribution primitive
the QBO read path (S27) and the AR summary (S13) consume.

TRUST THRESHOLD (owner decision, 2026-07-22, binding): disclose AR only when the
mapping ``status`` is ``CONFIRMED`` or ``AUTO_MATCHED``. ``NEEDS_REVIEW``,
``REJECTED``, a missing mapping, an ambiguous set we cannot disambiguate, or ANY
Gadget fault/timeout -> FAIL CLOSED (governed unavailable), never an empty success.

Same discipline as the Composio/EasyRoutes drivers:
- env-only credentials (``GADGET_API_KEY``/``GADGET_API_URL``), never committed;
- a per-CALL wall-clock deadline (NFR-8) via a single-worker ThreadPool that bounds
  the WHOLE attribution call, not one HTTP request (the S12 per-request-vs-per-call
  lesson);
- empty-vs-error distinguished: a successful empty result is "no mapping" (fail
  closed with a *cannot-attribute* message); a fault is ALSO fail closed — but never
  a silent empty success;
- total build (``build_qbo_attribution`` never raises): a missing key makes QBO
  customer-scoped reads fail closed per-call, it does NOT block the process from
  serving Shopify/etc. (mirrors EasyRoutes' owner-blocked token, S14).

=== WIRED to the owner's purpose-built endpoint (0.0.4 S28) ===
The owner shipped the stable read endpoint the S27 coupling ponytail called for:
``POST /internal/hermes/qbo-customer-mapping`` on ``paymentstatussync``. It takes ONE
Shopify GID in the body and returns, in a SINGLE call, both the forward mappings for
that GID and the ``reverse`` sets (for each canonical ``qboCustomerId`` in the forward
mappings, ALL rows sharing that canonical id) — so the forward resolve AND the A1
cross-customer collision guard run off one response, no second round-trip. The qbo id
is canonicalized server-side; Hermes treats it as an opaque canonical string. Auth is
``Authorization: Bearer <GADGET_API_KEY>``; a wrong/missing secret is a 401 (config
error, not "no mapping"). Confirmed live against the ``--development`` environment.

CONFIRMED (live 200): the request/response contract above and the two auth failures.
UNVERIFIED: the endpoint is deployed to ``development`` only — the owner still has to
push it to production and set ``GADGET_API_KEY`` there (the code DEFAULTS the base URL
to production; ``GADGET_API_URL`` overrides it for the dev wire-test). Every
governance / deadline / fail-closed path below is unit-tested against a fake client.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Optional, Protocol, runtime_checkable

from ..errors import ToolDriverError

API_URL_ENV = "GADGET_API_URL"
API_KEY_ENV = "GADGET_API_KEY"

# Default base URL is PRODUCTION (the owner reads production mappings). Overridable via
# ``GADGET_API_URL`` so the ``--development`` environment can be pointed at for the wire
# test without a code change. The route path is appended by the client; the env var (and
# this default) is the ORIGIN only.
DEFAULT_API_URL = "https://paymentstatussync.gadget.app"

# The owner's purpose-built read endpoint (S28). Body: {"shopifyGid": "<gid>"}; returns
# {"shopifyGid", "mappings": [...forward...], "reverse": {canonicalQboId: [...rows...]}}.
ENDPOINT_PATH = "/internal/hermes/qbo-customer-mapping"

# Per-CALL wall-clock budget (ms). Default matches Composio/EasyRoutes so all live
# backends degrade on the same envelope within one SMS turn (NFR-8).
DEADLINE_ENV = "GADGET_DEADLINE_MS"
DEFAULT_DEADLINE_MS = 8000.0

# Owner trust threshold: only these statuses may be disclosed against (binding).
TRUSTED_STATUSES: frozenset[str] = frozenset({"CONFIRMED", "AUTO_MATCHED"})


MappingResponse = tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]


@runtime_checkable
class GadgetClient(Protocol):
    """Injectable Gadget read seam (keeps unit tests off the network).

    ``fetch_mapping`` posts ONE Shopify GID to the owner's endpoint and returns
    ``(mappings, reverse)`` from a SUCCESSFUL, parsed 200: ``mappings`` = the forward
    rows for that GID (``{qboCustomerId, status}``), ``reverse`` = for each canonical
    ``qboCustomerId`` in ``mappings``, ALL rows sharing it (``{shopifyGid, status}``).
    Either may be empty (a genuine "no mapping"). It MUST raise
    :class:`ToolDriverError` on ANY fault (401/non-2xx, unparseable/unrecognized body)
    so an empty result is only ever a real "no mapping", never a masked error (the S26
    empty-vs-error trap).
    """

    def fetch_mapping(self, shopify_gid: str) -> MappingResponse: ...


def _clean(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        if isinstance(value, (int,)):
            value = str(value)
        else:
            return None
    value = value.strip()
    return value or None


def _canonical_qbo_id(value: Any) -> Optional[str]:
    """A QBO customer id in the owner app's canonical form, or None.

    Mirrors the app's ``canonicalQboCustomerIdKey``
    (``api/utils/qboCustomerMappingIndex.ts``): trim, and collapse a numeric string
    to its integer form so ``"4902"``, ``4902``, ``" 4902 "`` and ``"004902"`` all
    compare equal. A non-numeric id is returned trimmed as-is. This only aligns
    REPRESENTATION — it never maps two genuinely different ids together, so it
    cannot turn a non-match into a match (no disclosure risk); it only stops a
    legitimate customer being denied their OWN invoices over ``"4902"`` vs ``4902``.

    ponytail: integer ids only (QBO customer ids are integers). A non-integer
    numeric like ``"4902.0"`` falls through to the string branch rather than being
    truncated the way the app's ``Number()`` would — safe (fails toward non-match),
    upgrade to float-trunc parity only if such ids ever appear.
    """
    if isinstance(value, bool):  # bool is an int subclass but never a customer id
        return None
    if isinstance(value, int):
        return str(value)
    text = _clean(value)
    if text is None:
        return None
    try:
        return str(int(text))
    except ValueError:
        return text


def _normalize_gid(value: Any) -> Optional[str]:
    """A Shopify customer id in canonical gid form, or None.

    Tolerates a bare numeric id (``"1001"`` -> ``gid://shopify/Customer/1001``) so a
    mapping row that stored the short form still joins.
    """
    text = _clean(value)
    if text is None:
        return None
    if text.startswith("gid://"):
        return text
    return f"gid://shopify/Customer/{text}"


def _is_trusted(record: dict[str, Any]) -> bool:
    return str(record.get("status") or "").strip() in TRUSTED_STATUSES


def _resolve_forward_qbo_id(records: list[dict[str, Any]]) -> str:
    """The single canonical ``qboCustomerId`` these trusted forward rows agree on, else FAIL CLOSED.

    OWNER DECISION 2026-07-23 (binding): if one Shopify GID has trusted mappings to
    TWO DIFFERENT QBO customer ids (e.g. ``{4902, CONFIRMED}`` AND ``{3690,
    AUTO_MATCHED}``), Hermes FAILS CLOSED — it does NOT pick the CONFIRMED one. Any two
    DISTINCT trusted canonical qbo ids -> ambiguous -> raise, regardless of status. The
    trust FILTER stays ``{CONFIRMED, AUTO_MATCHED}``; only the conflict RESOLUTION
    changed (the old ``lockedByUser``/``CONFIRMED``/confidence preference is gone).

    ponytail: a future explicit ``lockedByUser`` override could let the owner pin one
    id and resolve the conflict deliberately — NOT now; the owner ruled fail-closed.
    """
    distinct = {_canonical_qbo_id(r.get("qboCustomerId")) for r in records}
    distinct.discard(None)
    if not distinct:
        raise ToolDriverError(
            "configuration_missing",
            "No trusted qboCustomerMapping resolves a qboCustomerId.",
        )
    if len(distinct) > 1:
        raise ToolDriverError(
            "configuration_missing",
            "Ambiguous qboCustomerMapping: this Shopify customer has trusted mappings "
            "to more than one QBO customer id; failing closed (owner decision "
            "2026-07-23).",
        )
    return next(iter(distinct))


class QboAttribution:
    """The S27 attribution primitive (S13 codes against this interface).

    Two directions, both under the same trust rule, both FAIL CLOSED on no mapping,
    unconfirmed/rejected status, ambiguity, or a Gadget fault/timeout:

    - :meth:`qbo_customer_id_for` — verified Shopify GID -> QBO customer id (for
      LISTING a customer's invoices / AR).
    - :meth:`invoice_owned_by` — a QBO customer id (from ``invoice.CustomerRef.value``)
      -> is it owned by this verified GID (for SCOPING a single response).

    ``config_error`` is set when built without a key: every method fails closed with
    that governed error instead of touching a backend (so a missing Gadget key makes
    QBO customer-scoped reads unavailable per-call, never a silent empty success, and
    never blocks the rest of the process — mirrors EasyRoutes, S14).
    """

    def __init__(
        self,
        client: Optional[GadgetClient],
        *,
        deadline_ms: Optional[float] = None,
        config_error: Optional[ToolDriverError] = None,
    ) -> None:
        self._client = client
        self._deadline_ms = deadline_ms
        self._config_error = config_error

    def qbo_customer_id_for(self, verified_gid: str) -> str:
        """Resolve the verified customer's QBO customer id, or FAIL CLOSED.

        ONE endpoint call gives both the forward mappings and the reverse sets. Keep
        only trusted forward rows, disambiguate (fail closed on two distinct trusted
        ids — owner decision 2026-07-23), then run the A1 collision guard off the SAME
        response. Raises (governed unavailable) on no trusted mapping, ambiguity,
        collision, or a Gadget fault — never returns an unattributed guess.
        """
        forward, reverse = self._fetch(verified_gid)
        return self._resolve(forward, reverse, verified_gid)

    def _resolve(
        self,
        forward: list[dict[str, Any]],
        reverse: dict[str, list[dict[str, Any]]],
        verified_gid: str,
    ) -> str:
        trusted = [r for r in forward if _is_trusted(r)]
        qbo_id = _resolve_forward_qbo_id(trusted)
        # A1 collision guard (cross-customer disclosure). Listing EVERY invoice billed
        # to ``qbo_id`` is only safe if ``qbo_id`` belongs to exactly this verified
        # customer. The endpoint's ``reverse[qbo_id]`` is every row sharing that
        # canonical qbo id — if a SECOND trusted Shopify GID appears there, listing
        # would hand customer B's invoices to A. Read it off the SAME response (no
        # second round-trip) and FAIL CLOSED unless the sole trusted owner is this GID.
        self._assert_sole_trusted_owner(qbo_id, reverse.get(qbo_id, []), verified_gid)
        return qbo_id

    @staticmethod
    def _assert_sole_trusted_owner(
        qbo_id: str, reverse_rows: list[dict[str, Any]], verified_gid: str
    ) -> None:
        """Fail closed unless ``qbo_id`` maps back to exactly this one verified GID."""
        trusted_gids = {
            _normalize_gid(r.get("shopifyGid"))
            for r in reverse_rows
            if _is_trusted(r)
        }
        trusted_gids.discard(None)
        if trusted_gids != {_normalize_gid(verified_gid)}:
            raise ToolDriverError(
                "configuration_missing",
                "qboCustomerId maps to more than one trusted Shopify customer; "
                "refusing to disclose to avoid cross-customer disclosure.",
            )

    def invoice_owned_by(self, qbo_customer_id: str, verified_gid: str) -> bool:
        """Whether the QBO customer behind an invoice maps to this verified GID.

        Resolve the verified customer's own sole trusted qbo id (forward + collision
        guard, off one endpoint call) and compare it to the invoice's qbo id. True
        when they match; False when the verified customer is attributable to a
        DIFFERENT qbo id (positively not theirs). Raises (fail closed) on no trusted
        mapping, ambiguity, collision, or a Gadget fault — the caller then does not
        disclose. This routes the single path through the SAME forward-resolution as
        the list path, so the owner's fail-closed-on-two-distinct-ids ruling applies
        to both (a Si-Li-shaped customer fails closed either way).
        """
        forward, reverse = self._fetch(verified_gid)
        resolved = self._resolve(forward, reverse, verified_gid)
        return resolved == _canonical_qbo_id(qbo_customer_id)

    def health(self) -> None:
        """Ping affordance for the S16 probe: a bounded read that must not fault.

        Posts a sentinel gid that matches nothing; an empty ``(mappings, reverse)`` is
        a healthy "reachable + authorized". Raises the governed error if the backend
        is unconfigured, unreachable, or unauthorized.
        """
        self._fetch("gid://shopify/Customer/__healthcheck__")

    def _fetch(self, verified_gid: str) -> MappingResponse:
        """Run one endpoint call under the per-CALL wall-clock deadline (NFR-8).

        The whole logical call is bounded by one budget in a worker thread; on expiry
        the worker is abandoned and the call fails closed as a governed timeout (the
        S12 per-request-vs-per-call finding). A ``ToolDriverError`` the client already
        classified propagates unchanged; anything else becomes governed so no raw
        error leaks (ADR-0136).
        """
        if self._config_error is not None or self._client is None:
            raise self._config_error or ToolDriverError(
                "configuration_missing", "Gadget attribution is not configured."
            )
        deadline = self._deadline_ms if self._deadline_ms is not None else _deadline_ms()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self._client.fetch_mapping, verified_gid)
            try:
                return future.result(timeout=deadline / 1000)
            except FutureTimeoutError as err:
                raise ToolDriverError(
                    "vendor_timeout",
                    f"Gadget attribution exceeded the {deadline:.0f}ms deadline.",
                ) from err
            except ToolDriverError:
                raise
            except Exception as err:  # noqa: BLE001 - convert ANY error to governed
                raise ToolDriverError(
                    "configuration_missing", f"Gadget attribution call failed: {err}"
                ) from err
        finally:
            pool.shutdown(wait=False)


def _deadline_ms() -> float:
    raw = os.environ.get(DEADLINE_ENV, "").strip()
    if not raw:
        return DEFAULT_DEADLINE_MS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_DEADLINE_MS


def gadget_configured() -> bool:
    """Whether the Gadget API key is present (for the S15/S16 health surface)."""
    return bool(os.environ.get(API_KEY_ENV))


def build_qbo_attribution() -> QboAttribution:
    """Build the attribution primitive from the environment. TOTAL — never raises.

    A missing ``GADGET_API_KEY`` yields an attributor that fails CLOSED per call with
    a governed ``configuration_missing`` (so QBO customer-scoped reads become
    unavailable, never a silent empty success), while leaving the rest of the
    process — Shopify/Square/etc. — serving. No network at build time.
    """
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        return QboAttribution(
            None,
            config_error=ToolDriverError(
                "configuration_missing",
                f"Gadget attribution is not configured; set {API_KEY_ENV} "
                f"(and optionally {API_URL_ENV}) in the deployment env.",
            ),
        )
    base = (os.environ.get(API_URL_ENV) or DEFAULT_API_URL).strip()
    return QboAttribution(_HttpGadgetClient(base_url=base, api_key=api_key))


class _HttpGadgetClient:
    """Live client for the owner's mapping endpoint over stdlib ``urllib`` (no new dep).

    NOT unit-tested — it needs the network and the owner's secret, exactly like the
    Composio SDK adapter and the EasyRoutes HTTP client. Its whole job is: POST the
    verified GID, parse ``{mappings, reverse}``, and turn every failure into a
    governed :class:`ToolDriverError` so no raw vendor/HTTP error leaks (ADR-0136). A
    successful-but-empty ``{"mappings": [], "reverse": {}}`` is a genuine "no mapping"
    (returns ``([], {})``); any fault (401/non-2xx, unparseable/unrecognized body)
    raises rather than masquerading as "no mapping" -> empty success.

    Tenant scoping is done server-side (the endpoint resolves the shop), so no shop
    filter is sent from here.
    """

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._url = base_url.rstrip("/") + ENDPOINT_PATH
        self._api_key = api_key

    def fetch_mapping(self, shopify_gid: str) -> MappingResponse:
        payload = json.dumps({"shopifyGid": shopify_gid}).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Gadget sits behind Cloudflare, which blocks the default
                # ``Python-urllib`` User-Agent with a 403 "Error 1010" BEFORE the
                # request ever reaches the route (masquerading as an auth failure).
                # A named UA clears the bot-signature block. ponytail: a plain
                # identifier is enough for the 1010 rule; no browser spoofing needed.
                "User-Agent": "toee-hermes/0.0.4 (+gadget-attribution)",
            },
            method="POST",
        )
        socket_timeout = _deadline_ms() / 1000
        try:
            with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as err:
            error_class = (
                "auth_expired" if err.code in (401, 403) else "configuration_missing"
            )
            raise ToolDriverError(
                error_class, f"Gadget HTTP {err.code} for {self._url}."
            ) from err
        except urllib.error.URLError as err:
            raise ToolDriverError(
                "vendor_timeout", f"Gadget request failed: {err.reason}."
            ) from err

        try:
            parsed = json.loads(body)
        except (ValueError, TypeError) as err:
            raise ToolDriverError(
                "configuration_missing", "Gadget returned an unparseable body."
            ) from err

        return _mappings_and_reverse(parsed)


def _mappings_and_reverse(parsed: Any) -> MappingResponse:
    """Extract ``(mappings, reverse)`` from the endpoint's 200 body, or FAIL CLOSED.

    Only an affirmatively recognized ``{mappings: list, reverse: dict}`` (possibly
    empty) yields data; any other shape — an ``error`` field, a missing/wrong-typed
    key — raises rather than masquerading as "no mapping" (the S26 empty-vs-error
    trap). The 401 body carries ``error`` but is already raised at the HTTP layer;
    this guards a 200 that doesn't match the contract.
    """
    if not isinstance(parsed, dict) or parsed.get("error"):
        raise ToolDriverError(
            "configuration_missing", "Gadget returned an unexpected shape."
        )
    mappings = parsed.get("mappings")
    reverse = parsed.get("reverse")
    if not isinstance(mappings, list) or not isinstance(reverse, dict):
        raise ToolDriverError(
            "configuration_missing",
            "Gadget response shape not recognized as a mapping result.",
        )
    return mappings, reverse

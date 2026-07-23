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

=== UNVERIFIED against the live Gadget API — needs the owner's key to confirm ===
The ``qboCustomerMapping`` FIELD names are confirmed from the app's own
``schema.gadget.ts`` (reliable) and the filter shape from the app's own
``api.qboCustomerMapping.findMany({ filter: { qboCustomerId: { equals } } })``
calls (``api/actions/syncStoreCredits.ts`` et al.). What still needs a live probe
(the key is owner-blocked, not in ``.env``) is isolated to :class:`_HttpGadgetClient`
and marked ``UNVERIFIED``: the GraphQL endpoint path, the auth header, the read
query name (``qboCustomerMappings``) and its connection envelope, and — critically —
whether an external API key is even granted ``read`` on this model (the app's
``accessControl/permissions.gadget.ts`` grants it to NO role today). Every governance
/ deadline / fail-closed path below is unit-tested against a fake client and does not
depend on the wire shape.

ponytail: COUPLING ceiling — Hermes reads the app's INTERNAL ``qboCustomerMapping``
model directly, so if the app renames/reshapes it, attribution breaks. Upgrade path:
the owner exposes a purpose-built, stable read endpoint (a Gadget action/route
returning ``{qboCustomerId, shopifyCustomerGid, status}``) and this module points at
it instead of the raw model API.
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
# Optional single-tenant scoping. The model ``belongsTo shopifyShop`` (multi-tenant
# in the app), but Toee is one shop; set this to also filter by shop id when the
# owner's key is app-scoped rather than shop-scoped. Unset -> no shop filter.
SHOP_ID_ENV = "GADGET_SHOP_ID"

# UNVERIFIED default: the production Gadget app's standard GraphQL endpoint. The
# app is ``paymentstatussync.gadget.app`` (shopify.app.toml). Overridable so a
# staging/dev environment (``--development`` subdomain) can be pointed at without a
# code change.
DEFAULT_API_URL = "https://paymentstatussync.gadget.app/api/graphql"

# Per-CALL wall-clock budget (ms). Default matches Composio/EasyRoutes so all live
# backends degrade on the same envelope within one SMS turn (NFR-8).
DEADLINE_ENV = "GADGET_DEADLINE_MS"
DEFAULT_DEADLINE_MS = 8000.0

# Owner trust threshold: only these statuses may be disclosed against (binding).
TRUSTED_STATUSES: frozenset[str] = frozenset({"CONFIRMED", "AUTO_MATCHED"})


@runtime_checkable
class GadgetClient(Protocol):
    """Injectable Gadget read seam (keeps unit tests off the network).

    ``query_customer_mappings`` returns the raw ``qboCustomerMapping`` records that
    match the given key from a SUCCESSFUL, parsed response — possibly an empty list.
    It MUST raise :class:`ToolDriverError` on ANY fault (missing auth, non-2xx,
    GraphQL errors, unparseable/unrecognized body) so an empty list is only ever a
    genuine "no mapping", never a masked error (the S26 empty-vs-error trap).

    Exactly one of ``shopify_customer_gid`` / ``qbo_customer_id`` is supplied.
    """

    def query_customer_mappings(
        self,
        *,
        shopify_customer_gid: Optional[str] = None,
        qbo_customer_id: Optional[str] = None,
    ) -> list[dict[str, Any]]: ...


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


def _preference(record: dict[str, Any]) -> tuple[int, int, float]:
    """Owner tie-break: prefer ``lockedByUser``, then ``CONFIRMED``, then confidence."""
    confidence = record.get("matchConfidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else -1.0
    return (
        1 if record.get("lockedByUser") else 0,
        1 if str(record.get("status") or "").strip() == "CONFIRMED" else 0,
        confidence,
    )


def _resolve_single(records: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """Pick the one trusted record whose ``key`` is unambiguous, else FAIL CLOSED.

    ``records`` are the trusted subset. Distinct non-empty values of ``key`` that
    AGREE collapse to one answer. If they disagree, the owner tie-break
    (:func:`_preference`) must yield a STRICT winner; a genuine tie between
    different values is ambiguous -> raise (never guess whose financial data this is).
    """
    candidates = [r for r in records if _clean(r.get(key)) is not None]
    if not candidates:
        raise ToolDriverError(
            "configuration_missing",
            f"No trusted qboCustomerMapping resolves '{key}'.",
        )
    distinct = {_clean(r.get(key)) for r in candidates}
    if len(distinct) == 1:
        return candidates[0]
    ranked = sorted(candidates, key=_preference, reverse=True)
    top, runner_up = ranked[0], ranked[1]
    if _preference(top) == _preference(runner_up) and _clean(top.get(key)) != _clean(
        runner_up.get(key)
    ):
        raise ToolDriverError(
            "configuration_missing",
            f"Ambiguous qboCustomerMapping for '{key}'; cannot safely disambiguate.",
        )
    return top


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

        Query by ``shopifyCustomerGid``, keep only trusted statuses, disambiguate,
        return ``qboCustomerId``. Raises (governed unavailable) on no trusted
        mapping, ambiguity, or a Gadget fault — never returns an unattributed guess.
        """
        records = self._query(shopify_customer_gid=verified_gid)
        trusted = [r for r in records if _is_trusted(r)]
        chosen = _resolve_single(trusted, "qboCustomerId")
        qbo_id = _canonical_qbo_id(chosen.get("qboCustomerId"))
        if qbo_id is None:
            raise ToolDriverError(
                "configuration_missing",
                "Trusted qboCustomerMapping has an empty qboCustomerId.",
            )
        # A1 collision guard (cross-customer disclosure). Listing EVERY invoice
        # billed to ``qbo_id`` is only safe if ``qbo_id`` belongs to exactly this
        # verified customer. The forward query above cannot see a many-GID ->
        # one-qbo_id collision (two trusted Shopify customers sharing a QBO id) —
        # it would hand customer B's invoices to A. Round-trip through the reverse
        # direction and FAIL CLOSED if more than one trusted Shopify GID maps back
        # to ``qbo_id``. This makes the forward/list path as fail-closed as the
        # reverse/single path already is.
        self._assert_sole_trusted_owner(qbo_id, verified_gid)
        return qbo_id

    def _assert_sole_trusted_owner(self, qbo_id: str, verified_gid: str) -> None:
        """Fail closed unless ``qbo_id`` maps back to exactly this one verified GID.

        One extra Gadget query (the reverse direction), deadline-bounded like every
        other ``_query``; a fault in it also fails closed. ponytail: worst case is
        2x the per-call deadline for a list — acceptable for a financial-disclosure
        guard; move to a single shared budget only if list latency ever bites.
        """
        reverse = self._query(qbo_customer_id=qbo_id)
        trusted_gids = {
            _normalize_gid(r.get("shopifyCustomerGid"))
            for r in reverse
            if _is_trusted(r)
        }
        trusted_gids.discard(None)
        if trusted_gids != {_normalize_gid(verified_gid)}:
            raise ToolDriverError(
                "configuration_missing",
                "qboCustomerId maps to more than one trusted Shopify customer; "
                "refusing to list to avoid cross-customer disclosure.",
            )

    def invoice_owned_by(self, qbo_customer_id: str, verified_gid: str) -> bool:
        """Whether the QBO customer behind an invoice maps to this verified GID.

        Query by ``qboCustomerId``, keep only trusted statuses, disambiguate to one
        ``shopifyCustomerGid``, compare. Returns False when it maps to a DIFFERENT
        customer (positively not theirs). Raises (fail closed) on no trusted mapping,
        ambiguity, or a Gadget fault — the caller then does not disclose.
        """
        records = self._query(qbo_customer_id=qbo_customer_id)
        trusted = [r for r in records if _is_trusted(r)]
        chosen = _resolve_single(trusted, "shopifyCustomerGid")
        return _normalize_gid(chosen.get("shopifyCustomerGid")) == _normalize_gid(
            verified_gid
        )

    def health(self) -> None:
        """Ping affordance for the S16 probe: a bounded read that must not fault.

        Runs a trivial trusted-mapping query (a sentinel gid that matches nothing);
        an empty list is a healthy "reachable + authorized". Raises the governed
        error if the backend is unconfigured, unreachable, or unauthorized.
        """
        self._query(shopify_customer_gid="gid://shopify/Customer/__healthcheck__")

    def _query(
        self,
        *,
        shopify_customer_gid: Optional[str] = None,
        qbo_customer_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Run one client query under the per-CALL wall-clock deadline (NFR-8).

        The whole logical call (however many HTTP requests the client makes) is
        bounded by one budget in a worker thread; on expiry the worker is abandoned
        and the call fails closed as a governed timeout (the S12 per-request-vs-per-
        call finding). A ``ToolDriverError`` the client already classified propagates
        unchanged; anything else becomes governed so no raw error leaks (ADR-0136).
        """
        if self._config_error is not None or self._client is None:
            raise self._config_error or ToolDriverError(
                "configuration_missing", "Gadget attribution is not configured."
            )
        deadline = self._deadline_ms if self._deadline_ms is not None else _deadline_ms()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(
                self._client.query_customer_mappings,
                shopify_customer_gid=shopify_customer_gid,
                qbo_customer_id=qbo_customer_id,
            )
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
    shop_id = _clean(os.environ.get(SHOP_ID_ENV))
    return QboAttribution(_HttpGadgetClient(url=base, api_key=api_key, shop_id=shop_id))


# The read query. UNVERIFIED: the connection field name and node fields must be
# confirmed against the live schema — but they mirror the app's own model API
# (``api.qboCustomerMapping``), and Gadget pluralizes the model for its GraphQL
# read connection, so ``qboCustomerMappings`` is the expected name.
_MAPPING_NODE_FIELDS = (
    "id qboCustomerId shopifyCustomerGid status matchConfidence lockedByUser"
)
_MAPPING_QUERY = (
    "query($filter: QboCustomerMappingFilter, $first: Int) {"
    "  qboCustomerMappings(filter: $filter, first: $first) {"
    f"    edges {{ node {{ {_MAPPING_NODE_FIELDS} }} }}"
    "  }"
    "}"
)


class _HttpGadgetClient:
    """Live Gadget GraphQL client over stdlib ``urllib`` (no new dependency).

    NOT unit-tested — it needs the network and the owner's key, exactly like the
    Composio SDK adapter and the EasyRoutes HTTP client. Its whole job is: build the
    filter, POST the read query, parse, and turn every failure into a governed
    :class:`ToolDriverError` so no raw vendor/HTTP error leaks (ADR-0136). A
    successful-but-empty connection is a genuine "no mapping" (returns ``[]``); any
    fault raises.

    UNVERIFIED — every wire detail here (endpoint path, auth header, query name,
    filter input type, connection envelope, AND whether the API key is even granted
    ``read`` on the model) must be confirmed against a live response before cutover.
    Fail-closed if any guess is wrong: an unrecognized body raises rather than
    returning ``[]`` (which would masquerade as "no mapping" -> empty success).
    """

    def __init__(self, *, url: str, api_key: str, shop_id: Optional[str]) -> None:
        self._url = url
        self._api_key = api_key
        self._shop_id = shop_id

    def _headers(self) -> dict[str, str]:
        # UNVERIFIED: Gadget API keys authenticate as ``Authorization: Bearer <key>``.
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _filter(
        self, *, shopify_customer_gid: Optional[str], qbo_customer_id: Optional[str]
    ) -> dict[str, Any]:
        # UNVERIFIED filter shape — mirrors the app's own findMany filters
        # (``{ qboCustomerId: { equals } }``), which is the reliable part.
        conditions: list[dict[str, Any]] = []
        if shopify_customer_gid is not None:
            conditions.append({"shopifyCustomerGid": {"equals": shopify_customer_gid}})
        if qbo_customer_id is not None:
            conditions.append({"qboCustomerId": {"equals": qbo_customer_id}})
        if self._shop_id is not None:
            conditions.append({"shop": {"id": {"equals": self._shop_id}}})
        if not conditions:
            # A query with no key would return the whole table — refuse rather than
            # over-fetch another customer's mapping (fail closed).
            raise ToolDriverError(
                "configuration_missing",
                "Gadget mapping query requires a shopify gid or qbo customer id.",
            )
        return conditions[0] if len(conditions) == 1 else {"AND": conditions}

    def query_customer_mappings(
        self,
        *,
        shopify_customer_gid: Optional[str] = None,
        qbo_customer_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        payload = json.dumps(
            {
                "query": _MAPPING_QUERY,
                "variables": {
                    "filter": self._filter(
                        shopify_customer_gid=shopify_customer_gid,
                        qbo_customer_id=qbo_customer_id,
                    ),
                    "first": 25,
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self._url, data=payload, headers=self._headers(), method="POST"
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

        return _records_from_envelope(parsed)


def _records_from_envelope(parsed: Any) -> list[dict[str, Any]]:
    """Extract mapping nodes from the GraphQL envelope, or FAIL CLOSED.

    A GraphQL ``errors`` array is a fault, not "no mapping" — raise (the S26
    empty-vs-error trap). Only an affirmatively recognized connection (possibly
    empty) yields ``[]``; any other shape raises rather than masquerading as empty.
    """
    if not isinstance(parsed, dict):
        raise ToolDriverError(
            "configuration_missing", "Gadget returned an unexpected shape."
        )
    if parsed.get("errors"):
        raise ToolDriverError(
            "configuration_missing", "Gadget GraphQL returned errors."
        )
    data = parsed.get("data")
    if not isinstance(data, dict):
        raise ToolDriverError(
            "configuration_missing", "Gadget response carried no data object."
        )
    connection = data.get("qboCustomerMappings")
    if not isinstance(connection, dict) or not isinstance(
        connection.get("edges"), list
    ):
        raise ToolDriverError(
            "configuration_missing",
            "Gadget response shape not recognized as a mapping connection.",
        )
    records: list[dict[str, Any]] = []
    for edge in connection["edges"]:
        node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict):
            records.append(node)
    return records

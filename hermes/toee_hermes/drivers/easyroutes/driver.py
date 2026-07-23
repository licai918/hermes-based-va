"""EasyRoutes direct REST driver for ``toee_easyroutes_read`` (FR-20/21, NFR-6/8).

EasyRoutes is a Shopify-native delivery app that is NOT in Composio (0.0.4 S12
confirmed only three toolkits reach Composio). So delivery status is served by a
*direct* REST client here, wired as a per-tool overlay beside the Composio driver
(``_build_driver_selector``) — no new ``INTEGRATION_DRIVER`` axis (FR-20).

Read-only. The two v1 actions are account-scoped exactly like the mock
(``drivers/mock/easyroutes.py``): a Verified Customer (ADR-0043) plus an order
reference the customer owns; a missing/non-owned reference is a governed policy
block, never fabricated delivery facts (ADR-0020, FR-21). The output shape is the
mock's ``EasyroutesDelivery`` verbatim — parity is a code guarantee because both
paths build that same dataclass and project the same two dicts.

Fail-closed posture (FR-21, and the S26 empty-vs-error trap):

- A live backend fault (auth, non-2xx, timeout, unparseable body) raises
  :class:`ToolDriverError`, which dispatch renders as the governed Tool
  Unavailable Response — never a silent fallback to the mock in production.
- A *successful* empty response is a genuine "no delivery for this order", which
  surfaces as the SAME governed policy block the mock returns for a non-owned
  reference. Crucially, the client contract guarantees an empty list is ONLY ever
  a real 2xx-empty: any fault raises instead, so an error is never narrated as
  "no delivery" (ADR-0020).

Deadline (NFR-8): the WHOLE logical call — however many HTTP requests the client
makes to resolve one delivery — is bounded by one wall-clock budget
(``EASYROUTES_DEADLINE_MS``), mirroring the knowledge driver. This is a per-CALL
bound, not a per-request one (the S12 Composio finding: a per-request timeout
lets an N-request call outlive N× the advertised budget).

=== UNVERIFIED against the live API — must be confirmed before cutover ===
The owner is rotating the m2m token (it transited chat) and it is not in the env
yet, so no live probe has run. The GOVERNANCE, DEADLINE, and FAIL-CLOSED paths
below are fully unit-tested against a fake client and do not depend on the wire
shape. What a live probe (or the owner) must still confirm is isolated to three
spots, each marked ``UNVERIFIED``:
  1. the request: base URL + path + how the order reference is queried
     (:class:`_HttpEasyroutesClient`);
  2. the auth headers (:meth:`_HttpEasyroutesClient._headers`);
  3. the response field paths, above all the Shopify-customer ownership link
     (:func:`_delivery_from_raw` / :func:`_shopify_customer_gid`).
Do NOT weaken the ownership check to make a fixture pass — confirm the real field
first (the QBO ``shopify_customer_id`` bug this iteration already paid for was
exactly an assumed-but-absent ownership field).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from ...errors import ToolDriverError
from ..mock.easyroutes import EasyroutesDelivery

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ...execute import ToolRequest
    from ...tool_gate import ToolExecutionContext

EASYROUTES_READ_TOOL = "toee_easyroutes_read"

API_TOKEN_ENV = "EASYROUTES_API_TOKEN"
CLIENT_ID_ENV = "EASYROUTES_CLIENT_ID"
# Overridable so a smoke/staging run can point at a sandbox host without a code
# change. UNVERIFIED default host — confirm against the owner's EasyRoutes account.
API_BASE_ENV = "EASYROUTES_API_BASE"
DEFAULT_API_BASE = "https://app.routstr.com/api/v1"

# Per-CALL wall-clock budget (ms). Default matches the Composio driver's 8s so the
# two live backends degrade on the same envelope within one SMS turn (NFR-8).
DEADLINE_ENV = "EASYROUTES_DEADLINE_MS"
DEFAULT_DEADLINE_MS = 8000.0


@runtime_checkable
class EasyroutesClient(Protocol):
    """Injectable REST seam (keeps unit tests off the network).

    ``fetch_deliveries`` returns the raw delivery/stop records EasyRoutes holds
    for ``order_number`` from a SUCCESSFUL, parsed response — possibly an empty
    list. It MUST raise :class:`ToolDriverError` on ANY fault (missing auth,
    non-2xx, timeout, unparseable body) so that an empty list is only ever a
    genuine "no delivery", never a masked error (FR-21).
    """

    def fetch_deliveries(self, *, order_number: Optional[str]) -> list[dict[str, Any]]: ...


# --- field extraction (the single UNVERIFIED verification point) -------------


def _read(params: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _shopify_customer_gid(raw: dict[str, Any]) -> str:
    """Normalize the Shopify customer on a raw EasyRoutes record to gid form.

    This is THE ownership link (ADR-0043) and the field the S12/S26 lesson is
    about: it must exist in a real response and identify the delivery's owner.
    EasyRoutes builds its deliveries from Shopify orders, so the linkage is
    expected to be present natively — but the exact path is ``UNVERIFIED`` until a
    live response is probed. We read the plausible locations and normalize; a
    record with NO resolvable Shopify customer yields ``""`` (empty), which can
    never match a verified customer's gid, so an unattributable record fails
    closed as non-owned rather than leaking to the wrong customer.
    """
    # UNVERIFIED: confirm which of these the live payload actually carries.
    candidate = (
        raw.get("shopify_customer_id")
        or raw.get("shopifyCustomerId")
        or _nested(raw, "customer", "shopify_customer_id")
        or _nested(raw, "customer", "id")
        or _nested(raw, "order", "customer_id")
        or _nested(raw, "order", "customer", "id")
    )
    if not isinstance(candidate, (str, int)) or candidate == "":
        return ""
    text = str(candidate)
    if text.startswith("gid://"):
        return text
    return f"gid://shopify/Customer/{text}"


def _nested(raw: dict[str, Any], *path: str) -> Any:
    node: Any = raw
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _delivery_from_raw(raw: dict[str, Any]) -> EasyroutesDelivery:
    """Map one raw EasyRoutes record to the mock's contract dataclass.

    Reusing ``EasyroutesDelivery`` makes output parity with the mock a guarantee
    rather than a convention. Every field path here is ``UNVERIFIED``.
    """
    return EasyroutesDelivery(
        order_number=str(
            _read(raw, "order_number", "orderNumber", "order_name", "name") or ""
        ),
        shopify_customer_id=_shopify_customer_gid(raw),
        status=str(_read(raw, "status", "delivery_status", "deliveryStatus") or ""),
        stop_sequence=_int(raw, "stop_sequence", "stopSequence", "stop_number"),
        eta_window=str(_read(raw, "eta_window", "etaWindow", "eta") or ""),
        route_name=str(_read(raw, "route_name", "routeName") or ""),
    )


def _int(raw: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


# --- ownership + governance (ports the mock's contract exactly) --------------


def _require_verified_customer_id(context: "ToolExecutionContext") -> str:
    """The verified customer's Shopify id, or a governed policy block (ADR-0043)."""
    identity = getattr(context, "identity", None)
    if not isinstance(identity, dict) or identity.get("outcome") != "verified_customer":
        raise ToolDriverError(
            "policy_blocked", "EasyRoutes read requires a verified customer."
        )
    customer_id = identity.get("shopify_customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise ToolDriverError(
            "policy_blocked", "EasyRoutes read requires a verified customer."
        )
    return customer_id


def _find_owned_delivery(
    records: list[dict[str, Any]], customer_id: str, order_number: Optional[str]
) -> EasyroutesDelivery:
    """Resolve the one delivery the verified customer owns, else a policy block.

    A missing or non-owned order reference — including a genuinely EMPTY
    successful response — is a governed policy block, never fabricated delivery
    facts (mirrors the mock's ``findOwnedDelivery``; the empty case reaching here
    is already known to be a real 2xx-empty because the client raises on faults).
    """
    for record in records:
        delivery = _delivery_from_raw(record)
        if delivery.order_number == order_number and (
            delivery.shopify_customer_id == customer_id
        ):
            return delivery
    raise ToolDriverError(
        "policy_blocked",
        f"No delivery for order {order_number or '<missing>'} "
        "owned by the verified customer.",
    )


class EasyroutesDriver:
    """A :class:`toee_hermes.execute.ToolDriver` backed by the EasyRoutes REST API.

    ``config_error`` is set when the driver was built without credentials: the
    driver still constructs (so ``_build_driver_selector`` never raises and the
    other tools keep working) but every call fails closed with that governed
    error instead of reaching a backend or a mock (FR-21).
    """

    kind = "easyroutes"

    def __init__(
        self,
        client: Optional[EasyroutesClient],
        *,
        deadline_ms: Optional[float] = None,
        config_error: Optional[ToolDriverError] = None,
    ) -> None:
        self._client = client
        self._deadline_ms = deadline_ms
        self._config_error = config_error

    def execute(self, request: "ToolRequest", context: "ToolExecutionContext") -> Any:
        if self._config_error is not None or self._client is None:
            raise self._config_error or ToolDriverError(
                "configuration_missing", "EasyRoutes driver is not configured."
            )
        if request.tool != EASYROUTES_READ_TOOL:
            raise ToolDriverError(
                "configuration_missing",
                f"EasyRoutes driver does not serve '{request.tool}'.",
            )

        customer_id = _require_verified_customer_id(context)
        order_number = _read(request.params, "order_number", "orderNumber")
        records = self._fetch_bounded(order_number)
        delivery = _find_owned_delivery(records, customer_id, order_number)

        if request.action == "get_delivery_status":
            return {"order_number": delivery.order_number, "status": delivery.status}
        if request.action == "get_route_details":
            return {
                "order_number": delivery.order_number,
                "stop_sequence": delivery.stop_sequence,
                "eta_window": delivery.eta_window,
                "route_name": delivery.route_name,
            }
        # Catalog validation in execute_tool runs first, so an unknown action here
        # is a config gap, surfaced governed rather than as a raw raise.
        raise ToolDriverError(
            "configuration_missing",
            f"No EasyRoutes mapping for action '{request.action}'.",
        )

    def _fetch_bounded(self, order_number: Optional[str]) -> list[dict[str, Any]]:
        """Run the whole client call under one wall-clock deadline (NFR-8).

        The fetch runs in a worker thread and the budget bounds the ENTIRE logical
        call — every HTTP request the client makes — not one request (the S12
        per-request-vs-per-call finding). On expiry the worker is abandoned
        (``shutdown(wait=False)``, as the knowledge driver does) and the call fails
        closed as a governed timeout; a socket timeout on the client side stops the
        abandoned thread from lingering (belt-and-braces). A ``ToolDriverError`` the
        client already classified propagates unchanged; anything else becomes a
        governed API error so no raw error leaks (ADR-0136).
        """
        deadline = (
            self._deadline_ms if self._deadline_ms is not None else _deadline_ms()
        )
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self._client.fetch_deliveries, order_number=order_number)
            try:
                return future.result(timeout=deadline / 1000)
            except FutureTimeoutError as err:
                raise ToolDriverError(
                    "vendor_timeout",
                    f"EasyRoutes call exceeded the {deadline:.0f}ms deadline.",
                ) from err
            except ToolDriverError:
                raise
            except Exception as err:  # noqa: BLE001 - convert ANY error to governed
                raise ToolDriverError(
                    "configuration_missing", f"EasyRoutes call failed: {err}"
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


def easyroutes_configured() -> bool:
    """Whether the m2m credentials are present (for the S15/S16 health surface)."""
    return bool(os.environ.get(API_TOKEN_ENV) and os.environ.get(CLIENT_ID_ENV))


def build_easyroutes_driver() -> EasyroutesDriver:
    """Build the EasyRoutes driver from the environment. TOTAL — never raises.

    Deliberately does NOT raise on missing credentials (unlike
    ``build_composio_driver``): it is called eagerly from ``_build_driver_selector``
    for every ``INTEGRATION_DRIVER=composio`` boot, and raising there would escape
    plugin registration as an ungoverned exception AND couple the whole live boot
    to the EasyRoutes token (which the owner supplies separately at cutover). So a
    missing token yields a driver that fails CLOSED per call with a governed
    ``configuration_missing`` — delivery questions get the Tool Unavailable
    Response while Shopify/QBO/Square stay live (FR-21). No network at build time.
    """
    token = os.environ.get(API_TOKEN_ENV)
    client_id = os.environ.get(CLIENT_ID_ENV)
    if not token or not client_id:
        return EasyroutesDriver(
            None,
            config_error=ToolDriverError(
                "configuration_missing",
                "EasyRoutes credentials are not set; "
                f"set {API_TOKEN_ENV} and {CLIENT_ID_ENV} in the deployment env.",
            ),
        )
    base = (os.environ.get(API_BASE_ENV) or DEFAULT_API_BASE).rstrip("/")
    return EasyroutesDriver(
        _HttpEasyroutesClient(base=base, token=token, client_id=client_id)
    )


class _HttpEasyroutesClient:
    """Live REST client over stdlib ``urllib`` (no new dependency).

    NOT unit-tested — it needs the network and the live account, exactly like the
    Composio SDK adapter. Its whole job is (1) authenticate, (2) GET the
    deliveries for an order reference, (3) parse JSON, and turn every failure into
    a governed :class:`ToolDriverError` so no raw vendor/HTTP error leaks
    (ADR-0136). A per-socket timeout is set from the deadline as belt-and-braces;
    the authoritative per-CALL bound is the driver's ThreadPool wall-clock.

    UNVERIFIED — endpoint, query parameterization, and auth headers must be
    confirmed against a live response before cutover (see module docstring).
    """

    def __init__(self, *, base: str, token: str, client_id: str) -> None:
        self._base = base
        self._token = token
        self._client_id = client_id

    def _headers(self) -> dict[str, str]:
        # UNVERIFIED: confirm the m2m header names the account expects.
        return {
            "Authorization": f"Bearer {self._token}",
            "X-Client-Id": self._client_id,
            "Accept": "application/json",
        }

    def fetch_deliveries(self, *, order_number: Optional[str]) -> list[dict[str, Any]]:
        # UNVERIFIED: path + query. Query by the Shopify order reference the
        # customer supplies; ownership is enforced on the RESPONSE, not trusted
        # from this filter.
        query = urllib.parse.urlencode(
            {"order_name": order_number} if order_number else {}
        )
        url = f"{self._base}/deliveries" + (f"?{query}" if query else "")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        # ponytail: the socket timeout is the FULL per-call deadline, which is
        # correct as long as this method makes exactly ONE request (the
        # ThreadPool wall-clock in EasyroutesDriver._fetch_bounded is the
        # authoritative per-CALL bound either way). If fetch_deliveries ever
        # fans out to N requests, an abandoned socket per request could linger
        # up to (N-1)x the deadline past the governed timeout -- divide this
        # by the expected request count, or track remaining wall-clock across
        # requests, before adding a second request here (the S12 per-request-
        # vs-per-call lesson).
        socket_timeout = _deadline_ms() / 1000
        try:
            with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as err:
            # Distinguish auth so the health surface can flag a rotated/expired
            # token (S15/S16), but stay fail-closed either way.
            error_class = "auth_expired" if err.code in (401, 403) else "configuration_missing"
            raise ToolDriverError(
                error_class, f"EasyRoutes HTTP {err.code} for {url}."
            ) from err
        except urllib.error.URLError as err:
            raise ToolDriverError(
                "vendor_timeout", f"EasyRoutes request failed: {err.reason}."
            ) from err

        try:
            parsed = json.loads(body)
        except (ValueError, TypeError) as err:
            # A body we cannot parse is a FAULT, not "no delivery" — fail closed
            # rather than return an empty list (the S26 empty-vs-error trap, FR-21).
            raise ToolDriverError(
                "configuration_missing", "EasyRoutes returned an unparseable body."
            ) from err

        # UNVERIFIED: the records may be top-level or under a wrapper key.
        if isinstance(parsed, list):
            # Recognized shape (including a genuinely empty list): honest
            # "no delivery", never a masked error.
            return parsed
        if isinstance(parsed, dict):
            for key in ("deliveries", "data", "results"):
                records = parsed.get(key)
                if isinstance(records, list):
                    # Recognized shape, honest empty included. Deliberately
                    # `isinstance(..., list)` and NOT `parsed.get(key) or ...`:
                    # an `or` chain treats `{"deliveries": []}` (a real,
                    # recognized empty result) as falsy and falls through to
                    # the unrecognized-shape branch below -- which used to
                    # `return []` there too, silently narrating a fault as
                    # "no delivery" (the exact QBO/Composio S26 trap this
                    # module's docstring warns about).
                    return records
            # A single object is one record.
            if any(k in parsed for k in ("order_number", "orderNumber", "status")):
                return [parsed]
            # Recognized-empty is ONLY a present list (top-level, or under
            # deliveries/data/results) or a single delivery object. Any other
            # dict shape is NOT a shape this parser affirmatively recognizes
            # as a delivery list -- it's a FAULT, not "no delivery". Fail
            # closed (governed unavailable) rather than fabricate an empty
            # result the persona would narrate as fact (FR-21). The live wire
            # shape is still UNVERIFIED, so lean conservative here.
            raise ToolDriverError(
                "configuration_missing",
                "EasyRoutes returned a body shape the parser does not recognize.",
            )
        raise ToolDriverError(
            "configuration_missing", "EasyRoutes returned an unexpected shape."
        )

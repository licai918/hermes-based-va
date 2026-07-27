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

Deadline (NFR-8): the WHOLE logical call — token exchange PLUS however many HTTP
requests the client makes — is bounded by one wall-clock budget
(``EASYROUTES_DEADLINE_MS``), mirroring the knowledge driver. This is a per-CALL
bound, not a per-request one (the S12 Composio finding: a per-request timeout
lets an N-request call outlive N× the advertised budget). The token exchange is an
EXTRA round trip and is inside that same bound.

=== VERIFIED live wire (0.0.4 S29) ===
The wire below was corrected to the owner's REAL EasyRoutes API and live-probed
against the ``toee-tire.myshopify.com`` account. The authoritative reference is the
owner's own Gadget app (``paymentstatussync``):

- Base: ``https://easyroutes.roundtrip.ai/api/2024-07`` (``EASYROUTES_API_BASE``).
- Auth: OAuth2 client-credentials token exchange —
  ``POST {base}/authenticate`` with ``{clientId, clientSecret}`` →
  ``{accessToken, expiresInSeconds, organization}`` → ``Authorization: Bearer``.
  Mirrors ``services/sameDay/listRoutesStopBackfillService.authenticateEasyRoutesAccessToken``.
- Reads: route-centric only — ``GET /routes`` (cursor-paginated list, stops inline)
  and ``GET /routes/{id}``. A benign static ``User-Agent`` is sent so Cloudflare
  does not 403 the default urllib agent (S28, Error 1010) — the live probe confirmed
  the header is accepted.

=== ORDER→DELIVERY LOOKUP IS AN OWNER DESIGN DECISION — NOT wired (S29 blocker) ===
There is NO per-order query in this API, and a live stop carries ``orderName`` /
``shopifyOrderId`` but NO Shopify-customer link. So a customer's order cannot be
resolved to a delivery here without either (a) an UNBOUNDED route scan on a
customer turn (forbidden, NFR-8) or (b) the owner's sync-to-DB + Shopify
order-ownership path (a whole subsystem Hermes does not have). Until the owner
picks a lookup shape, :meth:`_HttpEasyroutesClient.fetch_deliveries` FAILS CLOSED
with a governed error — never an unbounded scan, never fabricated facts, never a
weakened ownership check (the QBO ``shopify_customer_id`` bug this track already
paid for was exactly an assumed-but-absent ownership field). ``ping`` (auth + one
bounded route read) still gives the S16 health probe a true reachable+authorized
signal. The governance / deadline / fail-closed / mock-parity paths are unit-tested
against a fake client and define the contract the owner's eventual lookup must meet.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, runtime_checkable

from ...errors import ToolDriverError
from ..mock.easyroutes import EasyroutesDelivery

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ...execute import ToolRequest
    from ...tool_gate import ToolExecutionContext

EASYROUTES_READ_TOOL = "toee_easyroutes_read"

# The owner's app names the client secret ``EASYROUTES_SECRET`` (S29); the S14
# ``EASYROUTES_API_TOKEN`` is a fallback (both are set to the same value in the env).
SECRET_ENV = "EASYROUTES_SECRET"
API_TOKEN_ENV = "EASYROUTES_API_TOKEN"
CLIENT_ID_ENV = "EASYROUTES_CLIENT_ID"
# Overridable so a smoke/staging run can point at a sandbox host without a code
# change. Default is the owner's REAL base, live-verified in S29.
API_BASE_ENV = "EASYROUTES_API_BASE"
DEFAULT_API_BASE = "https://easyroutes.roundtrip.ai/api/2024-07"

# Cloudflare 403s the default Python-urllib User-Agent (S28, Error 1010). Send a
# benign static UA like the owner's Gadget client; the S29 live probe confirmed it
# is accepted by the token-exchange and route endpoints.
USER_AGENT = "ToeeTireHermes/0.0.4 (+https://toeetire.com)"

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

    def ping(self) -> None:
        """A cheap authenticated read for the S16 health probe. Returns on
        reachable+authorized; raises :class:`ToolDriverError` on any fault."""
        ...


# --- field extraction (maps a real route STOP to the mock contract) ----------


def _read(params: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _shopify_customer_gid(raw: dict[str, Any]) -> str:
    """Normalize the Shopify customer on a raw EasyRoutes record to gid form.

    This is THE ownership link (ADR-0043). S29 live-probed a real route stop and
    found it carries ``orderName`` / ``shopifyOrderId`` but NO Shopify-customer
    field — so a real stop is NOT self-attributable to a customer, and this returns
    ``""`` for it. That empty can never match a verified customer's gid, so a real
    stop fails closed as non-owned rather than leaking to the wrong customer. This
    absent-ownership-field is exactly WHY the order→delivery lookup is an owner
    design decision (see module docstring): resolving ownership needs the Shopify
    order→customer link, not a stop field. Do NOT weaken this to make a fixture pass
    (the QBO ``shopify_customer_id`` bug was this same assumed-but-absent field).
    The spellings below are the mock/contract shape plus plausible nestings, kept
    so the owner's eventual (order-scoped, ownership-checked) lookup can reuse it.
    """
    candidate = (
        raw.get("shopify_customer_id")
        or raw.get("shopifyCustomerId")
        or _nested(raw, "customer", "shopify_customer_id")
        or _nested(raw, "customer", "id")
        or _nested(raw, "shopifyOrder", "customer", "id")
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
    rather than a convention. Field spellings now include the REAL ones observed on
    a live route stop (S29): ``orderName``/``shopifyOrderId`` (order), ``deliveryStatus``
    (status), ``updatedArrival``/``plannedArrival`` (ETA), and the route's ``name``.
    A stop has no positional sequence field, so ``stop_sequence`` stays 0 for a real
    stop (the owner derives sequence from array position); the live API exposes no
    customer tracking-link field, so S14's FR-20 tracking-link gap stays open.
    """
    return EasyroutesDelivery(
        order_number=str(
            _read(raw, "order_number", "orderNumber", "orderName", "order_name", "name")
            or _int_str(raw, "shopifyOrderId")
            or ""
        ),
        shopify_customer_id=_shopify_customer_gid(raw),
        status=str(_read(raw, "status", "delivery_status", "deliveryStatus") or ""),
        stop_sequence=_int(raw, "stop_sequence", "stopSequence", "stop_number"),
        eta_window=str(
            _read(
                raw, "eta_window", "etaWindow", "eta", "updatedArrival", "plannedArrival"
            )
            or ""
        ),
        route_name=str(_read(raw, "route_name", "routeName", "name") or ""),
    )


def _int_str(raw: dict[str, Any], key: str) -> Optional[str]:
    """A non-zero ``shopifyOrderId`` as a string (live stops use "0" for none)."""
    value = raw.get(key)
    if isinstance(value, int) and value != 0:
        return str(value)
    if isinstance(value, str) and value not in ("", "0"):
        return value
    return None


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

    def health(self) -> None:
        """S16 probe: a bounded authenticated read that must not fault (FR-24).

        Delegates to the client's ``ping`` (token exchange + one cheap ``GET /routes``
        read) — reachable+authorized returns, any fault raises the governed
        :class:`ToolDriverError`. Deadline-bounded via ``_bounded`` like every other
        call, so the whole probe (auth + read) is under one wall-clock budget.
        """
        if self._config_error is not None or self._client is None:
            raise self._config_error or ToolDriverError(
                "configuration_missing", "EasyRoutes driver is not configured."
            )
        self._bounded(self._client.ping, "health")

    def _fetch_bounded(self, order_number: Optional[str]) -> list[dict[str, Any]]:
        return self._bounded(
            lambda: self._client.fetch_deliveries(order_number=order_number), "fetch"
        )

    def _bounded(self, call: Callable[[], Any], label: str) -> Any:
        """Run the whole client call under one wall-clock deadline (NFR-8).

        The call runs in a worker thread and the budget bounds the ENTIRE logical
        call — the token exchange PLUS every HTTP request the client makes — not one
        request (the S12 per-request-vs-per-call finding). On expiry the worker is
        abandoned (``shutdown(wait=False)``, as the knowledge driver does) and the
        call fails closed as a governed timeout; a socket timeout on the client side
        stops the abandoned thread from lingering (belt-and-braces). A
        ``ToolDriverError`` the client already classified propagates unchanged;
        anything else becomes a governed API error so no raw error leaks (ADR-0136).
        """
        deadline = (
            self._deadline_ms if self._deadline_ms is not None else _deadline_ms()
        )
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(call)
            try:
                return future.result(timeout=deadline / 1000)
            except FutureTimeoutError as err:
                raise ToolDriverError(
                    "vendor_timeout",
                    f"EasyRoutes {label} exceeded the {deadline:.0f}ms deadline.",
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


def _secret() -> Optional[str]:
    """The client secret: ``EASYROUTES_SECRET`` (owner naming), else the S14
    ``EASYROUTES_API_TOKEN`` fallback (both env vars hold the same value)."""
    return os.environ.get(SECRET_ENV) or os.environ.get(API_TOKEN_ENV)


def easyroutes_configured() -> bool:
    """Whether the m2m credentials are present (for the S15/S16 health surface)."""
    return bool(_secret() and os.environ.get(CLIENT_ID_ENV))


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
    secret = _secret()
    client_id = os.environ.get(CLIENT_ID_ENV)
    if not secret or not client_id:
        return EasyroutesDriver(
            None,
            config_error=ToolDriverError(
                "configuration_missing",
                "EasyRoutes credentials are not set; "
                f"set {SECRET_ENV} (or {API_TOKEN_ENV}) and {CLIENT_ID_ENV} "
                "in the deployment env.",
            ),
        )
    base = (os.environ.get(API_BASE_ENV) or DEFAULT_API_BASE).rstrip("/")
    return EasyroutesDriver(
        _HttpEasyroutesClient(base=base, client_id=client_id, secret=secret)
    )


class _HttpEasyroutesClient:
    """Live REST client for the owner's REAL EasyRoutes API over stdlib ``urllib``.

    Wire mirrors the owner's canonical Gadget client
    (``paymentstatussync`` ``services/sameDay/listRoutesStopBackfillService``):
    OAuth2 client-credentials token exchange at ``POST {base}/authenticate`` with
    ``{clientId, clientSecret}`` → ``{accessToken, expiresInSeconds, organization}``,
    then ``Authorization: Bearer <accessToken>`` for route reads. A benign static
    ``User-Agent`` is sent so Cloudflare does not 403 the default urllib agent (S28).

    Every failure becomes a governed :class:`ToolDriverError` so no raw vendor/HTTP
    error leaks (ADR-0136). A per-socket timeout is set from the deadline as
    belt-and-braces; the authoritative per-CALL bound is the driver's ThreadPool
    wall-clock (which covers the token exchange too).

    NOT unit-tested end-to-end (needs the network + the live account); the S29 live
    probe confirmed auth + ``/routes`` reads. The ORDER→DELIVERY lookup is an owner
    design decision (module docstring), so :meth:`fetch_deliveries` fails closed.
    """

    # Refresh a bit before the server's ``expiresInSeconds`` to avoid using a token
    # that expires mid-request.
    _TOKEN_SAFETY_MARGIN_S = 60.0

    def __init__(self, *, base: str, client_id: str, secret: str) -> None:
        self._base = base
        self._client_id = client_id
        self._secret = secret
        self._token: Optional[str] = None
        self._token_expiry_monotonic = 0.0

    def _socket_timeout(self) -> float:
        return _deadline_ms() / 1000

    def _access_token(self) -> str:
        """Return a cached access token, or exchange credentials for a fresh one.

        ponytail: in-instance token cache, no lock. A driver is currently built per
        logical call/probe, so cross-call reuse is nil today; the cache only spares a
        re-auth WITHIN one multi-read call (the owner's eventual lookup). A race just
        re-authenticates — harmless. It never affects the deadline (the ThreadPool
        wall-clock bounds auth + reads together). Add a shared/locked cache only if a
        long-lived driver ever makes many calls.
        """
        if self._token and time.monotonic() < self._token_expiry_monotonic:
            return self._token
        url = f"{self._base}/authenticate"
        data = json.dumps(
            {"clientId": self._client_id, "clientSecret": self._secret}
        ).encode()
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        body = self._read(req, url)
        token = body.get("accessToken") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise ToolDriverError(
                "auth_expired", "EasyRoutes auth returned no accessToken."
            )
        expires_in = body.get("expiresInSeconds")
        ttl = float(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else 0.0
        self._token = token
        self._token_expiry_monotonic = time.monotonic() + max(
            0.0, ttl - self._TOKEN_SAFETY_MARGIN_S
        )
        return token

    def _read(self, req: "urllib.request.Request", url: str) -> Any:
        """Perform one request, govern every fault, return parsed JSON."""
        try:
            with urllib.request.urlopen(req, timeout=self._socket_timeout()) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            # Distinguish auth so the health surface can flag a rotated/expired
            # credential (S15/S16), but stay fail-closed either way.
            error_class = (
                "auth_expired" if err.code in (401, 403) else "configuration_missing"
            )
            raise ToolDriverError(
                error_class, f"EasyRoutes HTTP {err.code} for {url}."
            ) from err
        except urllib.error.URLError as err:
            raise ToolDriverError(
                "vendor_timeout", f"EasyRoutes request failed: {err.reason}."
            ) from err
        try:
            return json.loads(raw)
        except (ValueError, TypeError) as err:
            # An unparseable body is a FAULT, never "no delivery" (S26 trap, FR-21).
            raise ToolDriverError(
                "configuration_missing", "EasyRoutes returned an unparseable body."
            ) from err

    def _get(self, path: str) -> Any:
        token = self._access_token()
        url = f"{self._base}{path}"
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        return self._read(req, url)

    def ping(self) -> None:
        """S16 health: token exchange + one bounded ``GET /routes`` read.

        A recognized ``{"routes": [...]}`` shape (empty list included) is
        reachable+authorized. Any fault — bad creds (401/403 → ``auth_expired``),
        unreachable, or an unrecognized shape — raises the governed error, never a
        false ``ok`` (the empty-vs-error lesson; do NOT lie on a health surface).
        """
        body = self._get("/routes?query.limit=1&query.sortKey=UPDATED_AT")
        if not isinstance(body, dict) or not isinstance(body.get("routes"), list):
            raise ToolDriverError(
                "configuration_missing",
                "EasyRoutes /routes returned an unrecognized shape.",
            )

    def fetch_deliveries(self, *, order_number: Optional[str]) -> list[dict[str, Any]]:
        """S29 design blocker — fails closed; no per-order lookup exists.

        The real API is route-centric (no per-order query) and a live stop carries
        no Shopify-customer link, so a customer's order cannot be resolved to a
        delivery here without an unbounded route scan (forbidden, NFR-8) or the
        owner's sync-to-DB + Shopify order-ownership path. Rather than scan
        unboundedly or fabricate a "no delivery", fail closed until the owner wires
        a lookup shape (see module docstring).
        """
        del order_number
        raise ToolDriverError(
            "configuration_missing",
            "EasyRoutes order->delivery lookup is not wired: the API is "
            "route-centric (no per-order query) and a stop carries no customer "
            "link. Owner design decision pending (S29).",
        )

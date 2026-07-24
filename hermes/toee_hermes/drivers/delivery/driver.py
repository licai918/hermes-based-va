"""Delivery-promise driver for ``toee_delivery_promise`` (0.0.4 S31b).

Consumer of the owner's purpose-built, LIVE Gadget endpoint
``POST {GADGET_API_URL}/internal/hermes/delivery-promise`` — the SAME base + secret
the QBO attribution driver (:mod:`toee_hermes.drivers.gadget`) already uses, so this
driver and QBO share one config (``GADGET_API_URL`` + ``GADGET_API_KEY``). Wired as a
per-tool overlay beside Composio (``_build_driver_selector``), exactly like the
EasyRoutes driver — no new ``INTEGRATION_DRIVER`` axis.

Two v1 actions map to the endpoint's 2-way dispatch:

- ``get_order_delivery`` (Tier 2, by order): richer routed-order status than S30's
  Shopify-fulfillment Tier 1 — ``routeLabel``, ``estimatedReturnAt``, proof-of-delivery.
  Request ``{orderId, shopifyCustomerId}``; the endpoint ENFORCES
  ``order.customer.id === shopifyCustomerId`` and 404s a non-owned order without
  revealing existence.
- ``get_product_promise`` (Tier 3a, by customer + variant): a pre-/just-delivery
  PROMISE. Request ``{shopifyCustomerId, variantId, quantity?}``.

Ownership (ADR-0043): ``shopifyCustomerId`` is ALWAYS the VERIFIED customer's Shopify
id from the Session Identity Snapshot — never a model-supplied one. An unverified /
unmatched caller fails closed (``policy_blocked``) before any HTTP call.

Fail-closed spine (FR-21, ADR-0020):
- 4xx/5xx/timeout/None -> governed Tool Unavailable, never a fabricated delivery
  status/date. The endpoint's error classes map: 401/403 -> ``auth_expired``, 404
  (ownership mismatch) -> ``not_found`` (governed "no order found for you", no leak),
  503 (``temporarily_unavailable``) -> ``vendor_timeout``, 400 (``invalid_request``,
  our bug) / any other -> ``configuration_missing``.
- An EMPTY-but-successful 200 (Tier 3a ``address_missing`` / ``route_unavailable``) is
  a REAL answer relayed via the endpoint's own ``displayLine``/``disclaimer`` — NOT an
  error and NOT narrated as a positive delivery. The endpoint already returns
  customer-safe prose (``displayLine``, ``disclaimer``, ``statusHeadline``); this
  driver passes the tier block through verbatim rather than re-inventing phrasing.

Per-CALL wall-clock deadline (NFR-8) reuses the gadget deadline (``GADGET_DEADLINE_MS``)
via a single-worker ThreadPool that bounds the WHOLE call. Secret only from env, never
logged/committed. Static ``User-Agent`` avoids the Cloudflare 1010 block (S28).

The live HTTP client (:class:`_HttpDeliveryPromiseClient`) is NOT unit-tested (it needs
the network + the owner's secret, like the QBO gadget client); the live dev-endpoint
e2e is the separately-reported step. Every governance/deadline/fail-closed path below is
unit-tested against a fake client.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

from ...errors import ToolDriverError
from ..gadget import (
    API_KEY_ENV,
    API_URL_ENV,
    DEFAULT_API_URL,
    _deadline_ms,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ...execute import ToolRequest
    from ...tool_gate import ToolExecutionContext

DELIVERY_PROMISE_TOOL = "toee_delivery_promise"

# The owner's purpose-built endpoint (S31a). Same base + secret as the QBO mapping
# endpoint; only the route path differs.
ENDPOINT_PATH = "/internal/hermes/delivery-promise"

# Named UA so Cloudflare does not 403 the default ``Python-urllib`` agent (S28, 1010).
USER_AGENT = "toee-hermes/0.0.4 (+delivery-promise)"


@runtime_checkable
class DeliveryPromiseClient(Protocol):
    """Injectable endpoint seam (keeps unit tests off the network).

    ``fetch`` POSTs one request body and returns the parsed 200 body. It MUST raise
    :class:`ToolDriverError` — with the tier-appropriate class — on ANY fault (401/403
    ->auth_expired, 404->not_found, 503->vendor_timeout, other non-2xx / unparseable /
    unrecognized body -> configuration_missing) so a returned dict is only ever a real
    200 (including the empty-but-successful ``address_missing`` promise), never a masked
    error (the S26 empty-vs-error trap).
    """

    def fetch(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _read(params: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _numeric_customer_id(customer_id: str) -> str:
    """The verified Shopify customer id as the bare numeric id the endpoint compares.

    The endpoint enforces ``order.customer.id === shopifyCustomerId`` against Shopify's
    numeric customer id (Si Li = ``1019382595648``), so a snapshot gid is stripped to
    its numeric form before it is sent.
    """
    prefix = "gid://shopify/Customer/"
    return customer_id[len(prefix):] if customer_id.startswith(prefix) else customer_id


def _require_verified_numeric_id(context: "ToolExecutionContext") -> str:
    """The verified customer's numeric Shopify id, or a governed policy block (ADR-0043).

    Delivery lookups must never run for an unverified/unmatched caller: ``order.customer``
    ownership and the per-customer promise are meaningless without a verified id, so
    refuse rather than disclose or fabricate (FR-21).
    """
    identity = getattr(context, "identity", None)
    if not isinstance(identity, dict) or identity.get("outcome") != "verified_customer":
        raise ToolDriverError(
            "policy_blocked", "Delivery read requires a verified customer."
        )
    customer_id = identity.get("shopify_customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise ToolDriverError(
            "policy_blocked", "Delivery read requires a verified customer."
        )
    return _numeric_customer_id(customer_id)


class DeliveryPromiseDriver:
    """A :class:`toee_hermes.execute.ToolDriver` backed by the delivery-promise endpoint.

    ``config_error`` is set when built without a secret: the driver still constructs (so
    ``_build_driver_selector`` never raises and other tools keep working) but every call
    fails closed with that governed error instead of reaching a backend or a mock (FR-21).
    """

    kind = "delivery_promise"

    def __init__(
        self,
        client: Optional[DeliveryPromiseClient],
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
                "configuration_missing", "Delivery-promise driver is not configured."
            )
        if request.tool != DELIVERY_PROMISE_TOOL:
            raise ToolDriverError(
                "configuration_missing",
                f"Delivery-promise driver does not serve '{request.tool}'.",
            )

        # Verified-customer id (numeric) comes from the snapshot, never the model.
        shopify_customer_id = _require_verified_numeric_id(context)

        if request.action == "get_order_delivery":
            order_id = _read(request.params, "order_id", "orderId", "order_number", "orderNumber")
            if not order_id:
                raise ToolDriverError(
                    "policy_blocked", "get_order_delivery requires an order reference."
                )
            body = self._fetch({"orderId": order_id, "shopifyCustomerId": shopify_customer_id})
            return _shape_order_delivery(body, order_id)

        if request.action == "get_product_promise":
            variant_id = _read(request.params, "variant_id", "variantId")
            if not variant_id:
                raise ToolDriverError(
                    "policy_blocked", "get_product_promise requires a variant id."
                )
            payload: dict[str, Any] = {
                "shopifyCustomerId": shopify_customer_id,
                "variantId": variant_id,
            }
            quantity = _quantity(request.params)
            if quantity is not None:
                payload["quantity"] = quantity
            body = self._fetch(payload)
            return _shape_product_promise(body, variant_id)

        # Catalog validation in execute_tool runs first, so an unknown action here is a
        # config gap, surfaced governed rather than as a raw raise.
        raise ToolDriverError(
            "configuration_missing",
            f"No delivery-promise mapping for action '{request.action}'.",
        )

    def _fetch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one endpoint call under the per-CALL wall-clock deadline (NFR-8).

        The whole logical call is bounded by one budget in a worker thread; on expiry the
        worker is abandoned and the call fails closed as a governed timeout (the S12
        per-request-vs-per-call finding). A ``ToolDriverError`` the client already
        classified propagates unchanged; anything else becomes governed so no raw error
        leaks (ADR-0136).
        """
        deadline = self._deadline_ms if self._deadline_ms is not None else _deadline_ms()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self._client.fetch, payload)  # type: ignore[union-attr]
            try:
                return future.result(timeout=deadline / 1000)
            except FutureTimeoutError as err:
                raise ToolDriverError(
                    "vendor_timeout",
                    f"Delivery-promise call exceeded the {deadline:.0f}ms deadline.",
                ) from err
            except ToolDriverError:
                raise
            except Exception as err:  # noqa: BLE001 - convert ANY error to governed
                raise ToolDriverError(
                    "configuration_missing", f"Delivery-promise call failed: {err}"
                ) from err
        finally:
            pool.shutdown(wait=False)


def _quantity(params: dict[str, Any]) -> Optional[int]:
    value = params.get("quantity")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        n = int(value)
        return n if n > 0 else None
    return None


def _shape_order_delivery(body: dict[str, Any], order_id: str) -> dict[str, Any]:
    """Extract the Tier 2 delivery block, or FAIL CLOSED on an unexpected shape.

    Only an affirmatively-recognized ``delivery`` dict yields data; any other shape
    (an ``error`` field, a missing/wrong-typed block) raises rather than fabricating an
    all-None delivery (ADR-0020, the S26 empty-vs-error trap). The endpoint's block is
    already customer-safe (``statusHeadline``/``disclaimer``); it is passed through
    verbatim so the agent relays the endpoint's prose, not a re-invented enum phrasing.
    """
    delivery = body.get("delivery") if isinstance(body, dict) else None
    if body.get("error") or not isinstance(delivery, dict):
        raise ToolDriverError(
            "configuration_missing",
            "Delivery-promise returned an unexpected Tier 2 shape.",
        )
    return {
        "order_id": body.get("orderId") or order_id,
        "order_name": body.get("orderName"),
        "delivery": delivery,
    }


def _shape_product_promise(body: dict[str, Any], variant_id: str) -> dict[str, Any]:
    """Extract the Tier 3a promise block, or FAIL CLOSED on an unexpected shape.

    A cold-start ``address_missing`` / ``route_unavailable`` status INSIDE the block is a
    real success relayed verbatim (its own ``displayLine``/``disclaimer``), NOT an error —
    only a missing/wrong-typed block or an ``error`` field fails closed.
    """
    promise = body.get("productDeliveryPromise") if isinstance(body, dict) else None
    if body.get("error") or not isinstance(promise, dict):
        raise ToolDriverError(
            "configuration_missing",
            "Delivery-promise returned an unexpected Tier 3a shape.",
        )
    return {
        "variant_id": body.get("variantId") or variant_id,
        "quantity": body.get("quantity"),
        "business_date": body.get("businessDate"),
        "timezone": body.get("timezone"),
        "product_delivery_promise": promise,
    }


def delivery_promise_configured() -> bool:
    """Whether the shared Gadget secret is present (for the S15/S16 health surface)."""
    return bool(os.environ.get(API_KEY_ENV))


def build_delivery_promise_driver() -> DeliveryPromiseDriver:
    """Build the driver from the environment. TOTAL — never raises.

    Mirrors ``build_easyroutes_driver``/``build_qbo_attribution``: a missing
    ``GADGET_API_KEY`` yields a driver that fails CLOSED per call (delivery questions get
    the Tool Unavailable Response) while Shopify/QBO/Square stay live. No network at
    build time. Reuses the SAME base env + secret as the QBO gadget driver.
    """
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        return DeliveryPromiseDriver(
            None,
            config_error=ToolDriverError(
                "configuration_missing",
                f"Delivery-promise endpoint is not configured; set {API_KEY_ENV} "
                f"(and optionally {API_URL_ENV}) in the deployment env.",
            ),
        )
    base = (os.environ.get(API_URL_ENV) or DEFAULT_API_URL).strip()
    return DeliveryPromiseDriver(_HttpDeliveryPromiseClient(base_url=base, api_key=api_key))


class _HttpDeliveryPromiseClient:
    """Live client for the owner's delivery-promise endpoint over stdlib ``urllib``.

    NOT unit-tested — it needs the network and the owner's secret, exactly like the QBO
    gadget client and the Composio SDK adapter. Its whole job: POST the request body,
    map every failure to the tier-appropriate governed :class:`ToolDriverError` so no raw
    vendor/HTTP error leaks (ADR-0136), and return the parsed 200 body (including the
    empty-but-successful ``address_missing`` promise) unchanged. A wrong/missing secret is
    a 401 -> ``auth_expired``; an ownership mismatch is a 404 -> ``not_found`` (no leak);
    a transient engine fault is a 503 -> ``vendor_timeout``.

    Tenant scoping is server-side (the endpoint resolves the shop), so no shop filter is
    sent from here.
    """

    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._url = base_url.rstrip("/") + ENDPOINT_PATH
        self._api_key = api_key

    def fetch(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        socket_timeout = _deadline_ms() / 1000
        try:
            with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as err:
            raise ToolDriverError(_http_error_class(err.code), f"Delivery HTTP {err.code}.") from err
        except urllib.error.URLError as err:
            raise ToolDriverError(
                "vendor_timeout", f"Delivery request failed: {err.reason}."
            ) from err

        try:
            parsed = json.loads(body)
        except (ValueError, TypeError) as err:
            raise ToolDriverError(
                "configuration_missing", "Delivery-promise returned an unparseable body."
            ) from err
        if not isinstance(parsed, dict):
            raise ToolDriverError(
                "configuration_missing", "Delivery-promise returned a non-object body."
            )
        return parsed


def _http_error_class(code: int) -> str:
    """Map an endpoint HTTP status to a governed error class (S31a contract)."""
    if code in (401, 403):
        return "auth_expired"
    if code == 404:  # ownership mismatch — governed "no order found", never a leak
        return "not_found"
    if code == 503:  # temporarily_unavailable — engine transient
        return "vendor_timeout"
    # 400 invalid_request (our bug) and any other non-2xx: fail closed, not "no delivery".
    return "configuration_missing"

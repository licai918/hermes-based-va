"""Composio Layer 1 integration driver (ADR-0127/0128/0130/0132/0136/0137).

Composio is an *internal* implementation backend behind the three Layer 1 Domain
Adapter Tools (ADR-0128); the agent surface, action enums, and public ``toee_*``
contracts are unchanged. This driver does NOT re-implement the Tool Gate:
:func:`toee_hermes.execute.execute_tool` validates the catalog and runs the gate
*before* calling :meth:`ComposioDriver.execute`, then converts any raised
:class:`ToolDriverError` into a governed Tool Unavailable Response. So the driver
just (1) maps the v1 ``(tool, action)`` to exactly one Composio toolkit action
(ADR-0130), (2) performs the backend call with the toolkit's Connected Account,
and (3) reshapes the raw vendor payload into the exact mock contract shape — never
leaking a raw vendor/OAuth error and never fabricating data (ADR-0020/0136).

The module top level imports cleanly WITHOUT the ``composio`` SDK installed
(ADR-0137): only :func:`build_composio_driver` touches the SDK, lazily.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

from ...errors import ToolDriverError

if TYPE_CHECKING:
    from ...execute import ToolRequest
    from ...tool_gate import ToolExecutionContext

# The only three v1 tools that may use Composio internally (ADR-0128 Layer 1).
COMPOSIO_LAYER1_TOOLS: tuple[str, ...] = (
    "toee_shopify_read",
    "toee_qbo_read",
    "toee_square_payment_link",
)

# Toolkit keys used both for the ``connected_accounts`` map and ``ActionSpec.app``.
SHOPIFY = "shopify"
QBO = "qbo"
SQUARE = "square"

# Per-toolkit Connected Account env var names (canonical: ops runbook + ADR-0137).
CONNECTED_ACCOUNT_ENV: dict[str, str] = {
    SHOPIFY: "COMPOSIO_SHOPIFY_CONNECTED_ACCOUNT_ID",
    QBO: "COMPOSIO_QBO_CONNECTED_ACCOUNT_ID",
    SQUARE: "COMPOSIO_SQUARE_CONNECTED_ACCOUNT_ID",
}


@runtime_checkable
class ComposioClient(Protocol):
    """Minimal, injectable Composio backend seam (keeps unit tests off the network).

    The live implementation wraps the Composio SDK in :func:`build_composio_driver`;
    tests pass a fake. ``execute_action`` returns the raw vendor data dict for one
    toolkit action, or raises (a :class:`ToolDriverError` to pre-classify the
    failure, or any exception which the driver wraps as ``composio_api_error``).
    """

    def execute_action(
        self,
        *,
        action: str,
        params: dict[str, Any],
        connected_account_id: str | None,
        user_id: str | None,
    ) -> dict[str, Any]: ...


RequestMapper = Callable[[dict[str, Any], "ToolExecutionContext"], dict[str, Any]]
# The response mapper also takes the context: ``get_product`` field-shaping and the
# Square payment-link thread id are context-dependent, and there is no post-driver
# shaping seam (the driver's return value IS the tool result).
ResponseMapper = Callable[[dict[str, Any], "ToolExecutionContext"], Any]


@dataclass(frozen=True)
class ActionSpec:
    """One-to-one mapping for a v1 ``(tool, action)`` (ADR-0130)."""

    app: str  # toolkit key -> connected account
    action_slug: str  # Composio toolkit action; exact slugs verified at staging smoke
    request_mapper: RequestMapper
    response_mapper: ResponseMapper


# --- shared mapping helpers --------------------------------------------------


def _read(params: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _shopify_numeric_customer_id(customer_id: str | None) -> str | None:
    """Shopify REST expects a numeric id string, not a GraphQL gid."""
    if not customer_id:
        return None
    prefix = "gid://shopify/Customer/"
    return customer_id[len(prefix) :] if customer_id.startswith(prefix) else customer_id


def _shopify_customer_gid(order: dict[str, Any]) -> str | None:
    """Normalize Composio/Shopify order payloads to the mock contract gid form."""
    customer_id = order.get("customer_id")
    if isinstance(customer_id, str) and customer_id.startswith("gid://"):
        return customer_id
    if customer_id is not None:
        return f"gid://shopify/Customer/{customer_id}"
    customer = order.get("customer")
    if isinstance(customer, dict) and customer.get("id") is not None:
        raw_id = customer["id"]
        if isinstance(raw_id, str) and raw_id.startswith("gid://"):
            return raw_id
        return f"gid://shopify/Customer/{raw_id}"
    return None


def _verified_customer_id(context: "ToolExecutionContext") -> str | None:
    """The verified customer's Shopify id from the Session Identity Snapshot (ADR-0043).

    Used only to *scope* the vendor query to the authorized owner; the gate has
    already authorized the read, so ``None`` here just means an unscoped query.
    """
    identity = getattr(context, "identity", None)
    if isinstance(identity, dict) and identity.get("outcome") == "verified_customer":
        customer_id = identity.get("shopify_customer_id")
        if isinstance(customer_id, str) and customer_id:
            return customer_id
    return None


def _is_verified(context: "ToolExecutionContext") -> bool:
    return _verified_customer_id(context) is not None


# --- shopify mappers ---------------------------------------------------------


def _shape_order(order: dict[str, Any]) -> dict[str, Any]:
    order_number = order.get("order_number") or order.get("name")
    return {
        "order_number": str(order_number) if order_number is not None else None,
        "customer_id": _shopify_customer_gid(order),
        "line_items": [
            {"sku": item.get("sku"), "title": item.get("title")}
            for item in (order.get("line_items") or [])
        ],
    }


def _shape_public_product(product: dict[str, Any]) -> dict[str, Any]:
    # Mock/eval fixtures already carry the public contract shape.
    if isinstance(product.get("product_id"), str) and product.get("product_url"):
        return {
            "product_id": product.get("product_id"),
            "sku": product.get("sku"),
            "title": product.get("title"),
            "product_url": product.get("product_url"),
            "media_url": product.get("media_url"),
        }
    variants = product.get("variants") or []
    sku = variants[0].get("sku") if variants else product.get("sku")
    handle = product.get("handle")
    product_id = product.get("product_id") or product.get("id")
    image = product.get("image") or {}
    media_url = image.get("src") if isinstance(image, dict) else product.get("media_url")
    product_url = product.get("product_url")
    if not product_url and handle:
        product_url = f"https://toee-tire.myshopify.com/products/{handle}"
    return {
        "product_id": str(product_id) if product_id is not None else None,
        "sku": sku,
        "title": product.get("title"),
        "product_url": product_url,
        "media_url": media_url,
    }


def _unwrap_composio_payload(raw: dict[str, Any]) -> dict[str, Any]:
    inner = raw.get("response_data")
    return inner if isinstance(inner, dict) else raw


def _shopify_get_order_request(
    params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    order_id = _read(params, "order_id", "orderId", "order_number", "orderNumber")
    return {"order_id": order_id}


def _shopify_get_order_response(raw: dict[str, Any], _ctx: "ToolExecutionContext") -> Any:
    payload = _unwrap_composio_payload(raw)
    order = payload.get("order", raw.get("order", raw))
    return _shape_order(order)


def _shopify_list_orders_request(
    _params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    # Composio defaults to open orders only; include fulfilled/cancelled for "last order".
    return {
        "customer_id": _shopify_numeric_customer_id(_verified_customer_id(context)),
        "status": "any",
    }


def _shopify_list_orders_response(raw: dict[str, Any], _ctx: "ToolExecutionContext") -> Any:
    payload = _unwrap_composio_payload(raw)
    orders = payload.get("orders") or raw.get("orders") or []
    return [_shape_order(order) for order in orders]


def _shopify_search_request(
    _params: dict[str, Any], _ctx: "ToolExecutionContext"
) -> dict[str, Any]:
    # SHOPIFY_GET_PRODUCTS lists the catalog; query filtering is a Toee gate concern.
    return {}


def _shopify_search_response(raw: dict[str, Any], _ctx: "ToolExecutionContext") -> Any:
    payload = _unwrap_composio_payload(raw)
    products = payload.get("products") or raw.get("products") or []
    return [_shape_public_product(product) for product in products]


def _shopify_get_product_request(
    params: dict[str, Any], _ctx: "ToolExecutionContext"
) -> dict[str, Any]:
    return {
        "product_id": _read(params, "product_id", "productId"),
        "sku": _read(params, "sku"),
    }


def _shopify_get_product_response(raw: dict[str, Any], context: "ToolExecutionContext") -> Any:
    payload = _unwrap_composio_payload(raw)
    product = payload.get("product", raw.get("product", payload))
    shaped = _shape_public_product(product)
    if _is_verified(context):
        variants = product.get("variants") or []
        shaped["price"] = product.get("price") or (
            variants[0].get("price") if variants else None
        )
        shaped["inventory"] = product.get("inventory") or (
            variants[0].get("inventory_quantity") if variants else None
        )
    return shaped


# --- qbo mappers -------------------------------------------------------------


def _shape_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
    return {
        "invoice_number": invoice.get("invoice_number"),
        "shopify_customer_id": invoice.get("shopify_customer_id"),
        "customer_email": invoice.get("customer_email"),
        "balance": invoice.get("balance"),
    }


def _qbo_invoice_from_raw(invoice: dict[str, Any]) -> dict[str, Any]:
    bill_email = invoice.get("BillEmail")
    email = (
        bill_email.get("Address")
        if isinstance(bill_email, dict)
        else invoice.get("customer_email")
    )
    return {
        "invoice_number": invoice.get("DocNumber") or invoice.get("invoice_number"),
        "shopify_customer_id": invoice.get("shopify_customer_id"),
        "customer_email": email,
        "balance": invoice.get("Balance", invoice.get("balance")),
    }


def _qbo_invoices_from_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    invoices = raw.get("invoices")
    if invoices is None:
        query_response = raw.get("QueryResponse") or {}
        invoices = query_response.get("Invoice") or raw.get("Invoice") or []
    if isinstance(invoices, dict):
        invoices = [invoices]
    return [_qbo_invoice_from_raw(invoice) for invoice in invoices]


# The Composio QBO list actions are not customer-scoped at the vendor (no
# Shopify->QBO CustomerRef bridge yet), so a verified customer could otherwise be
# handed another customer's invoices. Scope the *response* to the authorized owner
# by matching shopify_customer_id, and drop any invoice we cannot attribute to them
# (fail-safe: never return unattributable financial data to a customer).
def _invoice_owned_by_verified(
    invoice: dict[str, Any], context: "ToolExecutionContext"
) -> bool:
    verified_id = _verified_customer_id(context)
    return bool(verified_id) and invoice.get("shopify_customer_id") == verified_id


def _qbo_get_invoice_request(
    params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    invoice_number = _read(params, "invoice_number", "invoiceNumber")
    request: dict[str, Any] = {"max_results": 1}
    if invoice_number:
        # Sanitize before interpolating into the QBO query string (no quote breakout).
        safe = re.sub(r"[^A-Za-z0-9_.\-]", "", invoice_number)
        if safe:
            request["query"] = f"WHERE DocNumber = '{safe}'"
    return request


def _qbo_get_invoice_response(raw: dict[str, Any], context: "ToolExecutionContext") -> Any:
    if "invoice" in raw:
        invoice = _shape_invoice(raw["invoice"])
    else:
        invoices = _qbo_invoices_from_raw(raw)
        if invoices:
            invoice = invoices[0]
        elif raw.get("DocNumber") or raw.get("invoice_number"):
            invoice = _qbo_invoice_from_raw(raw)
        else:
            invoice = _shape_invoice(raw.get("invoice", raw))
    if not _invoice_owned_by_verified(invoice, context):
        raise ToolDriverError("not_found", "No matching invoice for this customer.")
    return invoice


def _qbo_list_invoices_request(
    _params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    # Response is scoped to the verified owner (see _qbo_list_invoices_response); the
    # capped fetch just bounds the page the vendor returns.
    _verified_customer_id(context)
    return {"max_results": 50}


def _qbo_list_invoices_response(raw: dict[str, Any], context: "ToolExecutionContext") -> Any:
    if "invoices" in raw and all(
        isinstance(invoice, dict) and "invoice_number" in invoice
        for invoice in raw["invoices"]
    ):
        invoices = [_shape_invoice(invoice) for invoice in raw["invoices"]]
    else:
        invoices = _qbo_invoices_from_raw(raw)
    return [inv for inv in invoices if _invoice_owned_by_verified(inv, context)]


# Fail-closed: the QBO Aged Receivables report is an all-customer aggregate, so a
# per-customer AR summary cannot be derived from it without misattributing other
# customers' balances. Gate the Composio path off until a customer-scoped QBO
# report (or an invoice-level Shopify->QBO bridge) exists; the mock driver still
# serves a correctly scoped summary for dev/eval.
_AR_SUMMARY_UNAVAILABLE = ToolDriverError(
    "configuration_missing",
    "Customer-scoped QuickBooks AR summary is unavailable on the live backend "
    "until a per-customer QBO report is wired.",
)


def _qbo_ar_summary_request(
    _params: dict[str, Any], _ctx: "ToolExecutionContext"
) -> dict[str, Any]:
    raise _AR_SUMMARY_UNAVAILABLE


def _qbo_ar_summary_response(raw: dict[str, Any], ctx: "ToolExecutionContext") -> Any:
    raise _AR_SUMMARY_UNAVAILABLE  # unreachable (request fails closed); defense in depth


# --- square mappers ----------------------------------------------------------


def _square_payment_link_request(
    params: dict[str, Any], _ctx: "ToolExecutionContext"
) -> dict[str, Any]:
    return {
        "invoice_number": _read(params, "invoice_number", "invoiceNumber"),
        "amount": params.get("amount"),
    }


def _square_payment_link_response(raw: dict[str, Any], context: "ToolExecutionContext") -> Any:
    link = raw.get("payment_link", raw)
    # The thread the link is delivered on is a Toee/Textline concept, not a Square
    # field: take it from the bound turn context (ADR-0022/0107), falling back to a
    # model-supplied param for the unbound path.
    conversation_id = getattr(context, "conversation_id", None)
    return {
        "payment_link_url": link.get("url"),
        "conversation_id": conversation_id,
        "amount": link.get("amount"),
    }


# --- one-to-one mapping table (ADR-0130) -------------------------------------
#
# Composio toolkit action slugs verified against live Shopify toolkit (staging smoke).
ACTION_MAPPING: dict[tuple[str, str], ActionSpec] = {
    ("toee_shopify_read", "get_order"): ActionSpec(
        SHOPIFY,
        "SHOPIFY_GET_ORDERSBY_ID",
        _shopify_get_order_request,
        _shopify_get_order_response,
    ),
    ("toee_shopify_read", "list_customer_orders"): ActionSpec(
        SHOPIFY,
        "SHOPIFY_GET_CUSTOMER_ORDERS",
        _shopify_list_orders_request,
        _shopify_list_orders_response,
    ),
    ("toee_shopify_read", "search_products"): ActionSpec(
        SHOPIFY,
        "SHOPIFY_GET_PRODUCTS",
        _shopify_search_request,
        _shopify_search_response,
    ),
    ("toee_shopify_read", "get_product"): ActionSpec(
        SHOPIFY, "SHOPIFY_GET_PRODUCT", _shopify_get_product_request, _shopify_get_product_response
    ),
    ("toee_qbo_read", "get_invoice"): ActionSpec(
        QBO, "QUICKBOOKS_QUERY_INVOICES", _qbo_get_invoice_request, _qbo_get_invoice_response
    ),
    ("toee_qbo_read", "list_customer_invoices"): ActionSpec(
        QBO,
        "QUICKBOOKS_LIST_INVOICES",
        _qbo_list_invoices_request,
        _qbo_list_invoices_response,
    ),
    ("toee_qbo_read", "get_ar_summary"): ActionSpec(
        QBO,
        "QUICKBOOKS_GET_AGED_RECEIVABLES_REPORT",
        _qbo_ar_summary_request,
        _qbo_ar_summary_response,
    ),
    ("toee_square_payment_link", "send_payment_link"): ActionSpec(
        SQUARE,
        "SQUARE_CREATE_PAYMENT_LINK",
        _square_payment_link_request,
        _square_payment_link_response,
    ),
}


class ComposioDriver:
    """A :class:`toee_hermes.execute.ToolDriver` backed by Composio toolkits."""

    kind = "composio"

    def __init__(
        self,
        client: ComposioClient,
        *,
        user_id: str | None,
        connected_accounts: dict[str, str],
    ) -> None:
        self._client = client
        self._user_id = user_id
        # toolkit key (shopify/qbo/square) -> connected_account_id
        self._connected_accounts = dict(connected_accounts)

    def execute(self, request: "ToolRequest", context: "ToolExecutionContext") -> Any:
        spec = ACTION_MAPPING.get((request.tool, request.action))
        if spec is None:
            # Any non-Layer-1 tool or unmapped action is a configuration gap, surfaced
            # as a governed failure (never a raw raise that escapes dispatch).
            raise ToolDriverError(
                "configuration_missing",
                f"No Composio Layer 1 mapping for '{request.tool}.{request.action}'.",
            )

        connected_account_id = self._connected_accounts.get(spec.app)
        if not connected_account_id:
            raise ToolDriverError(
                "configuration_missing",
                f"No Composio connected account configured for toolkit '{spec.app}'.",
            )

        vendor_params = spec.request_mapper(request.params, context)
        try:
            raw = self._client.execute_action(
                action=spec.action_slug,
                params=vendor_params,
                connected_account_id=connected_account_id,
                user_id=self._user_id,
            )
        except ToolDriverError:
            # The client already classified the failure (auth_expired/vendor_timeout/...).
            raise
        except Exception as err:  # noqa: BLE001 - convert ANY vendor/SDK error to governed
            # Never leak the raw vendor/Composio/OAuth error to the caller (ADR-0136);
            # the raw message stays on this exception for logs/audit only.
            raise ToolDriverError(
                "composio_api_error",
                f"Composio action '{spec.action_slug}' failed: {err}",
            ) from err

        return spec.response_mapper(raw, context)


def build_composio_driver() -> ComposioDriver:
    """Build the live Composio driver from environment configuration (ADR-0137).

    This is the ONLY place that imports the optional ``composio`` SDK, lazily, so
    ``import toee_hermes`` works without the SDK installed. A missing
    ``COMPOSIO_API_KEY`` (or absent SDK) is a governed ``configuration_missing``
    failure rather than a raw crash (ADR-0136).
    """
    api_key = os.environ.get("COMPOSIO_API_KEY")
    if not api_key:
        raise ToolDriverError(
            "configuration_missing",
            "COMPOSIO_API_KEY is not set; cannot build the Composio driver.",
        )

    user_id = os.environ.get("COMPOSIO_USER_ID")
    connected_accounts = {
        toolkit: os.environ.get(env_var)
        for toolkit, env_var in CONNECTED_ACCOUNT_ENV.items()
    }
    client = _build_sdk_client(api_key)
    return ComposioDriver(
        client,
        user_id=user_id,
        connected_accounts={k: v for k, v in connected_accounts.items() if v},
    )


def _toolkit_versions_from_env() -> dict[str, str]:
    """Read ``COMPOSIO_TOOLKIT_VERSION_<TOOLKIT>`` env vars (staging-smoke verified)."""
    prefix = "COMPOSIO_TOOLKIT_VERSION_"
    return {
        key[len(prefix) :].lower(): value
        for key, value in os.environ.items()
        if key.startswith(prefix) and value
    }


def _build_sdk_client(api_key: str) -> ComposioClient:
    """Lazily import the Composio SDK and wrap it behind :class:`ComposioClient`.

    Kept out of module import so ``toee_hermes`` stays dependency-free (ADR-0137);
    the exact SDK call surface and response envelope are verified at staging smoke.
    """
    try:
        from composio import Composio  # type: ignore  # optional dep, lazy (ADR-0137)
    except ImportError as err:
        raise ToolDriverError(
            "configuration_missing",
            "The composio SDK is not installed in this environment.",
        ) from err

    kwargs: dict[str, Any] = {"api_key": api_key}
    toolkit_versions = _toolkit_versions_from_env()
    if toolkit_versions:
        kwargs["toolkit_versions"] = toolkit_versions
    return _ComposioSdkClient(Composio(**kwargs))


class _ComposioSdkClient:
    """Thin adapter from the Composio SDK to the :class:`ComposioClient` Protocol.

    The exact SDK method, argument names, and response envelope
    (``successful``/``data``/``error``) are confirmed during staging smoke; any
    failure is translated to a governed :class:`ToolDriverError` so no raw vendor
    or Composio error leaks (ADR-0136). Untested here by design: it requires the
    SDK + network, which is a documented MANUAL smoke step, not a unit test.
    """

    def __init__(self, sdk: Any) -> None:
        self._sdk = sdk

    def execute_action(
        self,
        *,
        action: str,
        params: dict[str, Any],
        connected_account_id: str | None,
        user_id: str | None,
    ) -> dict[str, Any]:
        # ponytail: SDK surface verified at staging smoke; upgrade path is to pin the
        # exact Composio v3 method + envelope once confirmed against live toolkits.
        result = self._sdk.tools.execute(
            action,
            user_id=user_id,
            connected_account_id=connected_account_id,
            arguments=params,
        )
        if isinstance(result, dict):
            if result.get("successful") is False:
                raise ToolDriverError(
                    "composio_api_error",
                    f"Composio reported failure for '{action}': {result.get('error')}",
                )
            data = result.get("data")
            return data if isinstance(data, dict) else result
        return result  # type: ignore[return-value]

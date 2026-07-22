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

# Toee toolkit key -> Composio's own toolkit slug. The two differ for QuickBooks
# ("qbo" here, "quickbooks" upstream), and the version pin is keyed by the VENDOR
# slug on both sides: the SDK resolves a call's version with
# ``get_toolkit_version(tool.toolkit.slug, ...)`` and reads
# ``COMPOSIO_TOOLKIT_VERSION_<SLUG>`` from the environment. So
# COMPOSIO_TOOLKIT_VERSION_QBO would be silently ignored — hence this map rather
# than upper-casing our own key (0.0.4 S12).
TOOLKIT_SLUG: dict[str, str] = {SHOPIFY: "shopify", QBO: "quickbooks", SQUARE: "square"}

TOOLKIT_VERSION_ENV: dict[str, str] = {
    toolkit: f"COMPOSIO_TOOLKIT_VERSION_{slug.upper()}"
    for toolkit, slug in TOOLKIT_SLUG.items()
}

# NFR-8: one backend call must be bounded by the *turn's* deadline, not the
# vendor's. The SDK ships a 60s read timeout and retries on top, so an unbounded
# Composio call can outlive the whole SMS turn it was serving. Overridable via
# ``COMPOSIO_DEADLINE_MS``; on expiry the SDK raises, the driver converts it to a
# governed ``composio_api_error``, and dispatch renders the Tool Unavailable
# Response — never a fallback to mock.
DEADLINE_ENV = "COMPOSIO_DEADLINE_MS"
DEFAULT_DEADLINE_MS = 8000.0


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
    action_slug: str  # Composio toolkit action; slugs verified live (0.0.4 S12)
    request_mapper: RequestMapper | None = None
    response_mapper: ResponseMapper | None = None
    # Set when the live toolkit cannot serve this action. The driver raises it
    # INSTEAD of calling the backend, so the tool fails closed with a message
    # naming the reason rather than a vendor 404 (or worse, a mock payload) —
    # FR-21. The mappers are then dead and left unset; ``hermes_runtime.
    # composio_smoke`` reads this field to know which slugs not to probe.
    unavailable: ToolDriverError | None = None


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

# Fail-closed: Composio's Square toolkit has NO create-payment-link action. Not a
# version-pin gap — the 0.0.4 S12 surface probe found only SQUARE_RETRIEVE_PAYMENT_LINK
# at the pinned version, and a catalog-wide search for a Square create action at
# `latest` returns nothing either (other toolkits have one; Square does not). The
# previously mapped SQUARE_CREATE_PAYMENT_LINK 404s.
#
# ponytail: the ceiling is "Composio cannot create a Square payment link". Upgrade
# paths, in order of laziness: a Composio custom tool wrapping
# POST /v2/online-checkout/payment-links, or a direct Square REST driver as a
# per-tool overlay beside Composio — the same shape FR-20 uses for EasyRoutes.
# Until then this fails closed: a customer must never be sent a fabricated or
# mock payment link (ADR-0020, FR-21).
_SQUARE_PAYMENT_LINK_UNAVAILABLE = ToolDriverError(
    "configuration_missing",
    "Square payment links are unavailable on the live backend: the Composio Square "
    "toolkit exposes no create-payment-link action.",
)


# --- one-to-one mapping table (ADR-0130) -------------------------------------
#
# Every slug below resolves against the live toolkit at its pinned version —
# verified by `python -m hermes_runtime.composio_smoke` phase 2 (0.0.4 S12).
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
        unavailable=_AR_SUMMARY_UNAVAILABLE,
    ),
    ("toee_square_payment_link", "send_payment_link"): ActionSpec(
        SQUARE,
        "SQUARE_CREATE_PAYMENT_LINK",
        unavailable=_SQUARE_PAYMENT_LINK_UNAVAILABLE,
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

        if spec.unavailable is not None:
            # The live toolkit cannot serve this action; never reach the backend and
            # never fall through to a mock (FR-21). Checked before the connected
            # account so the message names the real reason, not a missing account.
            raise spec.unavailable

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
    failure rather than a raw crash (ADR-0136) — and, since 0.0.4 S12, so is a
    missing toolkit-version pin for any configured toolkit.
    """
    api_key = os.environ.get("COMPOSIO_API_KEY")
    if not api_key:
        raise ToolDriverError(
            "configuration_missing",
            "COMPOSIO_API_KEY is not set; cannot build the Composio driver.",
        )

    user_id = os.environ.get("COMPOSIO_USER_ID")
    connected_accounts = {
        toolkit: value
        for toolkit, env_var in CONNECTED_ACCOUNT_ENV.items()
        if (value := os.environ.get(env_var))
    }
    client = _build_sdk_client(api_key, pinned_toolkit_versions(connected_accounts))
    return ComposioDriver(
        client,
        user_id=user_id,
        connected_accounts=connected_accounts,
    )


def pinned_toolkit_versions(connected_accounts: dict[str, str]) -> dict[str, str]:
    """Version pin per *configured* toolkit, keyed by Composio's toolkit slug.

    Fails closed on a missing pin (0.0.4 S12). Left unpinned, the SDK resolves the
    toolkit to ``"latest"`` and then raises ``ToolVersionRequiredError`` from inside
    ``tools.execute`` — a governed failure, but one that arrives on a customer's
    turn and names neither the toolkit nor the env var. Raising here moves it to
    process boot, where the operator is the one reading the message.
    """
    versions: dict[str, str] = {}
    missing: list[str] = []
    for toolkit in connected_accounts:
        value = (os.environ.get(TOOLKIT_VERSION_ENV[toolkit]) or "").strip()
        if not value or value == "latest":
            missing.append(TOOLKIT_VERSION_ENV[toolkit])
        else:
            versions[TOOLKIT_SLUG[toolkit]] = value
    if missing:
        raise ToolDriverError(
            "configuration_missing",
            "Composio toolkit version pin missing or 'latest': "
            f"{', '.join(sorted(missing))}. Pin each configured toolkit to an "
            "exact version from the Composio dashboard.",
        )
    return versions


def deadline_seconds() -> float:
    """Per-call backend deadline in seconds (``COMPOSIO_DEADLINE_MS``, NFR-8)."""
    raw = os.environ.get(DEADLINE_ENV, "").strip()
    try:
        return (float(raw) if raw else DEFAULT_DEADLINE_MS) / 1000
    except ValueError:
        return DEFAULT_DEADLINE_MS / 1000


def _build_sdk_client(api_key: str, toolkit_versions: dict[str, str]) -> ComposioClient:
    """Lazily import the Composio SDK and wrap it behind :class:`ComposioClient`.

    Kept out of module import so ``toee_hermes`` stays dependency-free (ADR-0137).
    ``max_retries=0`` is deliberate: the SDK's default retries multiply the
    timeout, so retries would make ``deadline_seconds()`` a per-attempt bound
    instead of a per-call one (NFR-8). A transient 5xx therefore fails closed on
    this turn rather than eating the turn's whole budget.
    """
    try:
        from composio import Composio  # type: ignore  # optional dep, lazy (ADR-0137)
    except ImportError as err:
        raise ToolDriverError(
            "configuration_missing",
            "The composio SDK is not installed in this environment.",
        ) from err

    return _ComposioSdkClient(
        Composio(
            api_key=api_key,
            toolkit_versions=toolkit_versions,
            timeout=deadline_seconds(),
            max_retries=0,
        )
    )


class _ComposioSdkClient:
    """Thin adapter from the Composio SDK to the :class:`ComposioClient` Protocol.

    Pinned against ``composio`` 0.15.0 (the hermes-runtime dependency), 0.0.4 S12:

    - call surface — ``Tools.execute(slug, arguments, *, connected_account_id=None,
      user_id=None, version=None, ...)``. ``slug`` and ``arguments`` are positional;
      everything else is keyword-only.
    - envelope — ``ToolExecutionResponse``, a plain ``dict`` with exactly
      ``{"data": dict, "error": str | None, "successful": bool}``. The SDK
      ``model_dump()``s the HTTP response before returning, so it is never a model.
    - version — resolved per call from the SDK-level ``toolkit_versions`` map
      (see :func:`pinned_toolkit_versions`); an unpinned toolkit raises
      ``ToolVersionRequiredError`` here rather than silently drifting to latest.

    Every failure is translated to a governed :class:`ToolDriverError` so no raw
    vendor or Composio error leaks (ADR-0136). Not unit-tested: it needs the SDK
    plus network, which is what ``hermes_runtime.composio_smoke`` covers.
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
        result = self._sdk.tools.execute(
            action,
            params,
            connected_account_id=connected_account_id,
            user_id=user_id,
        )
        if not result.get("successful", False):
            raise ToolDriverError(
                "composio_api_error",
                f"Composio reported failure for '{action}': {result.get('error')}",
            )
        data = result.get("data")
        if not isinstance(data, dict):
            # Fail closed rather than hand a mapper an envelope it would silently
            # shape into an all-``None`` "result" (ADR-0020: never fabricate data).
            raise ToolDriverError(
                "composio_api_error",
                f"Composio returned no data object for '{action}'.",
            )
        return data

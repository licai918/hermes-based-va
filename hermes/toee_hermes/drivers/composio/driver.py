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
from ..base import resolve_integration_driver
from ..gadget import QboAttribution, _canonical_qbo_id, build_qbo_attribution
from ..qbo_ar import ar_summary

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
#
# The budget is for ONE ``execute_action``, not one HTTP request — see
# ``_ROUND_TRIPS_PER_EXECUTE``.
DEADLINE_ENV = "COMPOSIO_DEADLINE_MS"
DEFAULT_DEADLINE_MS = 8000.0

# HTTP requests the SDK makes for one ``Tools.execute`` call (composio 0.15.0,
# ``core/models/tools.py``), fix wave 1:
#
#   1. ``execute()``  -> ``client.tools.retrieve``  (cached in ``_tool_schemas``)
#   2. ``_execute_tool()`` -> ``get_raw_composio_tool_by_slug`` -> a SECOND
#      ``client.tools.retrieve``, which is NOT cached anywhere
#   3. ``client.tools.execute`` -- the actual vendor call
#
# The SDK ``timeout`` bounds one request, so passing the whole deadline made the
# real per-call bound 3x the advertised one (24 s at the 8 s default, since the
# driver is rebuilt per turn and cache 1 is always cold). Divide instead, so
# ``COMPOSIO_DEADLINE_MS`` is what NFR-8 says it is: the bound on one tool call.
# Measured live against the pinned Shopify toolkit (fix wave 1): a metadata
# retrieve is ~0.2-0.3 s and a full three-round-trip execute ~0.9 s, so the
# resulting 2.67 s per-request slice is ~3x the observed whole-call cost.
_ROUND_TRIPS_PER_EXECUTE = 3


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
    # QBO customer-scoped attribution mode (0.0.4 S27/S13). ``"single"`` / ``"list"``
    # / ``"ar_summary"`` tell the driver to enforce ownership via the Gadget bridge
    # AFTER the pure response mapper shapes the payload — these are the only actions
    # that disclose per-customer financial data, and the shaped invoice carries the
    # private ``qbo_customer_id`` the join needs. ``"ar_summary"`` scopes the list the
    # same way, then aggregates the owned invoices into the AR summary shape.
    ownership: str | None = None
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


# A normalized invoice carries the 4 public contract fields PLUS a private
# ``qbo_customer_id`` (the invoice's ``CustomerRef.value``) used only for
# attribution; :func:`_public_invoice` drops it before the result leaves the driver.
_PUBLIC_INVOICE_KEYS = (
    "invoice_number",
    "shopify_customer_id",
    "customer_email",
    "balance",
)


def _public_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
    return {key: invoice.get(key) for key in _PUBLIC_INVOICE_KEYS}


def _qbo_customer_id_of(invoice: dict[str, Any]) -> str | None:
    """The QBO customer id an invoice is billed to (``CustomerRef.value`` live), or None."""
    ref = invoice.get("CustomerRef")
    if isinstance(ref, dict) and ref.get("value"):
        return str(ref["value"])
    for key in ("qbo_customer_id", "customer_ref_value"):
        value = invoice.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    return None


def _direct_owner_gid(invoice: dict[str, Any]) -> str | None:
    """The invoice's Shopify owner in canonical gid form, when carried DIRECTLY.

    Present on mock/recorded/eval invoices (the mock sets ``shopify_customer_id``);
    absent on live QBO invoices, which carry only a QBO ``CustomerRef`` — those need
    the Gadget join instead. ``None`` here means "not directly attributable".
    """
    value = invoice.get("shopify_customer_id")
    if not isinstance(value, str) or not value:
        return None
    return value if value.startswith("gid://") else f"gid://shopify/Customer/{value}"


def _shape_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
    return {
        "invoice_number": invoice.get("invoice_number"),
        "shopify_customer_id": invoice.get("shopify_customer_id"),
        "customer_email": invoice.get("customer_email"),
        "balance": invoice.get("balance"),
        "qbo_customer_id": _qbo_customer_id_of(invoice),
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
        "qbo_customer_id": _qbo_customer_id_of(invoice),
    }


def _qbo_invoices_from_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    invoices = raw.get("invoices")
    if invoices is None:
        query_response = raw.get("QueryResponse") or {}
        invoices = query_response.get("Invoice") or raw.get("Invoice") or []
    if isinstance(invoices, dict):
        invoices = [invoices]
    return [_qbo_invoice_from_raw(invoice) for invoice in invoices]


def _require_verified_customer_id(context: "ToolExecutionContext") -> str:
    """Verified customer's Shopify id (canonical gid), or a governed policy block.

    QBO customer-scoped reads must never run unscoped; an unverified caller owns no
    invoices, so refuse rather than disclose or fabricate (ADR-0043, FR-21).
    """
    verified = _verified_customer_id(context)
    if not verified:
        raise ToolDriverError(
            "policy_blocked", "QuickBooks invoice reads require a verified customer."
        )
    return verified if verified.startswith("gid://") else f"gid://shopify/Customer/{verified}"


# --- QBO ownership (0.0.4 S27) -----------------------------------------------
#
# Live QBO invoices carry NO Shopify id — only ``CustomerRef.value`` (a QBO customer
# id). So ownership cannot be read off the invoice; it needs the authoritative
# Shopify<->QBO join in the owner's Gadget ``qboCustomerMapping`` model, under the
# owner's trust rule (CONFIRMED/AUTO_MATCHED only). Two paths, both fail closed:
#   - DIRECT linkage (mock/recorded/eval): compare ``shopify_customer_id`` — no
#     Gadget call, keeps the mock parity and existing recordings correct.
#   - LIVE (no direct linkage): join through the Gadget bridge. If it cannot
#     positively attribute (no trusted mapping / ambiguous / Gadget fault) it RAISES
#     -> governed unavailable, NEVER an empty "you have no invoices" (the S27 bug was
#     exactly that empty-success door).


def _qbo_owned_invoice(
    invoice: dict[str, Any],
    context: "ToolExecutionContext",
    attributor: "QboAttribution",
) -> dict[str, Any]:
    """Return the invoice's public shape if the verified customer owns it, else fail closed."""
    verified = _require_verified_customer_id(context)
    direct = _direct_owner_gid(invoice)
    if direct is not None:
        if direct == verified:
            return _public_invoice(invoice)
        raise ToolDriverError("not_found", "No matching invoice for this customer.")
    qbo_id = _canonical_qbo_id(invoice.get("qbo_customer_id"))
    if qbo_id is None:
        # No Shopify linkage and no QBO customer ref: unattributable -> never disclose.
        raise ToolDriverError("not_found", "Invoice ownership could not be verified.")
    # Reverse join under the trust rule; raises on fault/missing/ambiguous mapping.
    if attributor.invoice_owned_by(qbo_id, verified):
        return _public_invoice(invoice)
    raise ToolDriverError("not_found", "No matching invoice for this customer.")


def _qbo_owned_invoices(
    invoices: list[dict[str, Any]],
    context: "ToolExecutionContext",
    attributor: "QboAttribution",
) -> list[dict[str, Any]]:
    """The subset the verified customer owns, or fail closed if it cannot be attributed."""
    verified = _require_verified_customer_id(context)
    # Fast path: every invoice is directly attributable -> pure compare, no Gadget.
    if invoices and all(_direct_owner_gid(inv) is not None for inv in invoices):
        return [
            _public_invoice(inv) for inv in invoices if _direct_owner_gid(inv) == verified
        ]
    # Live path (incl. an empty vendor page): resolve the verified customer's QBO id
    # via the Gadget bridge and scope by it. Unresolvable -> RAISE (fail closed);
    # returning [] here would be the empty-success bug narrated as "you have none".
    qbo_id = attributor.qbo_customer_id_for(verified)
    owned: list[dict[str, Any]] = []
    for inv in invoices:
        direct = _direct_owner_gid(inv)
        if direct is not None:
            if direct == verified:
                owned.append(inv)
            continue
        inv_qbo = _canonical_qbo_id(inv.get("qbo_customer_id"))
        if inv_qbo is not None and inv_qbo == qbo_id:
            owned.append(inv)
    return [_public_invoice(inv) for inv in owned]


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
    # Shaping only (returns a normalized invoice); ownership is enforced by the driver
    # via the Gadget attributor (spec.ownership == "single").
    if "invoice" in raw:
        return _shape_invoice(raw["invoice"])
    invoices = _qbo_invoices_from_raw(raw)
    if invoices:
        return invoices[0]
    if raw.get("DocNumber") or raw.get("invoice_number"):
        return _qbo_invoice_from_raw(raw)
    return _shape_invoice(raw.get("invoice", raw))


def _qbo_list_invoices_request(
    _params: dict[str, Any], context: "ToolExecutionContext"
) -> dict[str, Any]:
    # Response is scoped to the verified owner via the Gadget bridge (see
    # _qbo_owned_invoices); the capped fetch just bounds the page the vendor returns.
    _verified_customer_id(context)
    return {"max_results": 50}


def _qbo_list_invoices_response(raw: dict[str, Any], context: "ToolExecutionContext") -> Any:
    # Shaping only (returns normalized invoices); ownership is enforced by the driver
    # via the Gadget attributor (spec.ownership == "list").
    if "invoices" in raw and all(
        isinstance(invoice, dict) and "invoice_number" in invoice
        for invoice in raw["invoices"]
    ):
        return [_shape_invoice(invoice) for invoice in raw["invoices"]]
    return _qbo_invoices_from_raw(raw)


# AR summary (0.0.4 S13, FR-19) is NOT derived from
# QUICKBOOKS_GET_AGED_RECEIVABLES_REPORT: that report is an ALL-customer aggregate
# and cannot be scoped to one customer without misattributing another customer's
# balance -- the exact disclosure S27 exists to prevent. Instead it reuses the S27
# per-customer list path (QUICKBOOKS_LIST_INVOICES + the Gadget attribution
# primitive) and aggregates the verified customer's OWN owned invoices via
# ``ar_summary``. All of S27's fail-closed arms (no mapping / unconfirmed /
# ambiguous / collision / Gadget fault or timeout) are inherited unchanged, so an
# unattributable summary is a governed unavailable, never a fabricated/empty "$0".
# See the ``ownership == "ar_summary"`` branch in ``ComposioDriver.execute``.

# Still fail-closed, but for a DIFFERENT reason than S12's (0.0.4 S26).
#
# The owner's 2026-07-22 decision moved this tool from create to RETRIEVE
# semantics: payment links are pre-created in the Square console and the agent
# only ever fetches an existing one. The action that implements that is real —
# ``SQUARE_RETRIEVE_PAYMENT_LINK`` resolves live at pin ``20260616_00`` and takes
# exactly one parameter, ``{"required": ["id"]}`` (S26 probe). So the ACTION is no
# longer the blocker. Two things still are, and both are product decisions rather
# than code:
#
#  1. LINK IDENTITY. Retrieve is by the Square-assigned payment link id
#     ("PAY_LINK_ID_123"). Nothing the agent legitimately holds maps to one — not
#     the verified ``shopify_customer_id``, not the QBO ``invoice_number``, not the
#     conversation id — and the toolkit exposes no list/search action to resolve
#     one at the pin (``SQUARE_LIST_PAYMENT_LINKS`` 404s), so not even a console
#     naming convention would help. The id can only come from owner-maintained
#     configuration, whose shape (one fixed link, or a per-invoice map) is the
#     owner's call. Letting the model supply the id is not an option: retrieving
#     the WRONG link texts a verified customer someone else's amount (ADR-0148 —
#     identity- and money-bearing values come from framework context, never the
#     model).
#  2. AMOUNT. The public contract returns ``amount`` and ADR-0066 has Hermes
#     confirm the amount before send. The retrieved ``PaymentLink`` carries only
#     ``orderId`` — no money field — so the amount needs a SECOND call
#     (``SQUARE_RETRIEVE_ORDER``), which ADR-0130 forbids for one v1 action.
#
# One more trap for whoever wires the mappers: the S26 probe's live execute
# returned ``successful: true`` with ``data = {"errors": [...], "payment_link":
# null}`` (the connected account is missing Square's ORDERS_READ scope). Composio
# calls a vendor-level error a success, and ``data`` IS a dict, so
# ``_ComposioSdkClient`` passes it straight through. The response mapper must fail
# closed on ``data["errors"]`` / a null link rather than shape an all-``None``
# result (ADR-0020). Note also that the live envelope is snake_case
# (``payment_link``) while the published schema says ``paymentLink``.
#
# ponytail: the ceiling is "Composio can retrieve a Square payment link, but
# nothing in this system knows WHICH one". Upgrade path: the owner names the
# link-identity source, after which this is an ordinary mapping (request mapper ->
# ``{"id": ...}``, response mapper -> ``payment_link.url``). Until then it fails
# closed: a customer must never be sent a fabricated, mock, or wrong-invoice
# payment link (ADR-0020, FR-21).
_SQUARE_PAYMENT_LINK_UNAVAILABLE = ToolDriverError(
    "configuration_missing",
    "Square payment links are unavailable on the live backend: the pre-created "
    "link to retrieve is not identified by anything this system knows.",
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
        QBO,
        "QUICKBOOKS_QUERY_INVOICES",
        _qbo_get_invoice_request,
        _qbo_get_invoice_response,
        ownership="single",
    ),
    ("toee_qbo_read", "list_customer_invoices"): ActionSpec(
        QBO,
        "QUICKBOOKS_LIST_INVOICES",
        _qbo_list_invoices_request,
        _qbo_list_invoices_response,
        ownership="list",
    ),
    ("toee_qbo_read", "get_ar_summary"): ActionSpec(
        QBO,
        # NOT the all-customer aged-receivables report (see note above): compute the
        # per-customer summary from the SAME list action + attribution S27 built, then
        # aggregate. Same slug, request mapper, and response mapper as
        # list_customer_invoices; ownership="ar_summary" scopes + aggregates.
        "QUICKBOOKS_LIST_INVOICES",
        _qbo_list_invoices_request,
        _qbo_list_invoices_response,
        ownership="ar_summary",
    ),
    ("toee_square_payment_link", "send_payment_link"): ActionSpec(
        SQUARE,
        # Retrieve, not create (0.0.4 S26 owner decision). This slug DOES resolve
        # at the pin — the smoke's surface phase probes it like any other — but the
        # action stays gated off until the link id has a governed source.
        "SQUARE_RETRIEVE_PAYMENT_LINK",
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
        attributor: "QboAttribution | None" = None,
    ) -> None:
        self._client = client
        self._user_id = user_id
        # toolkit key (shopify/qbo/square) -> connected_account_id
        self._connected_accounts = dict(connected_accounts)
        # QBO Shopify<->QBO attribution bridge (0.0.4 S27). Defaults to an
        # unconfigured attributor that fails closed per call, so a driver built
        # without a Gadget key still serves Shopify/Square and only QBO
        # customer-scoped reads that need the live join fail closed.
        self._attributor = attributor or _UNCONFIGURED_ATTRIBUTION

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

        shaped = spec.response_mapper(raw, context)
        # QBO customer-scoped attribution runs AFTER shaping (0.0.4 S27): the shaped
        # invoice carries the private qbo_customer_id the Gadget join needs. Both
        # arms fail closed on an unattributable read rather than disclosing or
        # emitting an empty success.
        if spec.ownership == "single":
            return _qbo_owned_invoice(shaped, context, self._attributor)
        if spec.ownership == "list":
            return _qbo_owned_invoices(shaped, context, self._attributor)
        if spec.ownership == "ar_summary":
            # Compute the AR summary from the verified customer's OWN owned invoices
            # (0.0.4 S13). _qbo_owned_invoices reuses S27's attribution and RAISES on
            # any unattributable read, so the summary fails closed exactly as listing
            # does -- never a fabricated/empty "$0". A positively-attributed customer
            # with zero open invoices yields an honest $0 (empty is not error here).
            verified = _require_verified_customer_id(context)
            owned = _qbo_owned_invoices(shaped, context, self._attributor)
            return ar_summary(verified, owned)
        return shaped


# Default attributor for a driver built without a Gadget key (unit tests, or a
# deployment where the owner-blocked Gadget key is not yet set). Any live-path QBO
# attribution through it fails closed; direct-linkage (mock/recorded) never reaches it.
_UNCONFIGURED_ATTRIBUTION = QboAttribution(
    None,
    config_error=ToolDriverError(
        "configuration_missing",
        "Gadget attribution is not configured; QuickBooks customer-scoped reads are "
        "unavailable until GADGET_API_KEY is set.",
    ),
)


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
    if not connected_accounts:
        # 0.0.4 S12 fix wave 2: with zero *_CONNECTED_ACCOUNT_ID set,
        # pinned_toolkit_versions({}) iterates nothing and finds nothing missing,
        # so this used to return a driver that boots clean and then raises
        # "configuration_missing" on every single tool call in ComposioDriver.execute
        # (line ~515) -- exactly the class of bug the boot gate exists to catch
        # (review Finding 4). A composio driver connected to no vendor account is
        # unusable, so fail closed here instead of on the first customer turn.
        raise ToolDriverError(
            "configuration_missing",
            "INTEGRATION_DRIVER=composio but no Composio connected account is "
            "configured; set at least one of: "
            f"{', '.join(sorted(CONNECTED_ACCOUNT_ENV.values()))}.",
        )
    client = _build_sdk_client(api_key, pinned_toolkit_versions(connected_accounts))
    return ComposioDriver(
        client,
        user_id=user_id,
        connected_accounts=connected_accounts,
        # Total build (never raises): a missing Gadget key yields an attributor that
        # fails QBO customer-scoped reads closed per call, not a boot failure (S27,
        # mirrors the EasyRoutes owner-blocked token, S14).
        attributor=build_qbo_attribution(),
    )


def pinned_toolkit_versions(connected_accounts: dict[str, str]) -> dict[str, str]:
    """Version pin per *configured* toolkit, keyed by Composio's toolkit slug.

    Fails closed on a missing pin (0.0.4 S12). Left unpinned, the SDK resolves the
    toolkit to ``"latest"`` and then raises ``ToolVersionRequiredError`` from inside
    ``tools.execute`` — a governed failure, but one that arrives on a customer's
    turn and names neither the toolkit nor the env var. Raising here moves it off
    the customer's turn; :func:`require_composio_configuration`, called from every
    composition root, is what actually moves it to process boot.
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


def composio_config_status() -> dict[str, dict[str, Any]]:
    """Per-toolkit config presence for the S15/S16 status surface. TOTAL, no secrets.

    Returns ``{toolkit_key: {configured, pinned_version, connected, api_key_present,
    account_env, version_env}}`` for each Layer-1 toolkit. Reports ONLY booleans and
    the version-pin STRING (a Composio toolkit version like ``"20250101"`` — a
    version, not a credential); it NEVER returns the API key or the connected-account
    id value (NFR-6, secret-scan gate).

    Deliberately never raises (unlike :func:`pinned_toolkit_versions`): a status read
    must SHOW a half-configured toolkit, not fail closed on it. ``configured`` mirrors
    exactly what a live call needs — the API key, that toolkit's connected account,
    and a real (non-``latest``) version pin — so green here means the tool would
    actually run, not merely that the code path exists.
    """
    api_key_present = bool(os.environ.get("COMPOSIO_API_KEY"))
    result: dict[str, dict[str, Any]] = {}
    for toolkit in TOOLKIT_SLUG:
        account_env = CONNECTED_ACCOUNT_ENV[toolkit]
        version_env = TOOLKIT_VERSION_ENV[toolkit]
        connected = bool(os.environ.get(account_env))
        pin = (os.environ.get(version_env) or "").strip()
        has_pin = bool(pin) and pin != "latest"
        result[toolkit] = {
            "configured": api_key_present and connected and has_pin,
            "pinned_version": pin if has_pin else None,
            "connected": connected,
            "api_key_present": api_key_present,
            "account_env": account_env,
            "version_env": version_env,
        }
    return result


def probe_composio_toolkit(toolkit_key: str) -> None:
    """S16 health probe for one Composio Layer-1 toolkit (FR-24).

    A cheap AUTHENTICATED connected-account status read -- NOT an action execution,
    so no vendor cost and no customer data crosses. Raises the governed
    :class:`ToolDriverError` on any fault (missing key/account, SDK absent, vendor
    error, or a connected account the vendor no longer reports). ``toolkit_key`` is
    one of ``shopify``/``qbo``/``square``.

    Owner-blocked today (needs ``COMPOSIO_API_KEY`` + the toolkit's connected
    account). UNVERIFIED wire: the SDK connected-account read surface
    (``client.connected_accounts.get``) must be confirmed against the live API at
    cutover -- isolated here, exactly like the ``_ComposioSdkClient`` execute path.
    The per-call deadline is applied by the S16 probe runner's ThreadPool wrapper.
    """
    account_env = CONNECTED_ACCOUNT_ENV[toolkit_key]
    connected_account_id = os.environ.get(account_env)
    if not connected_account_id:
        raise ToolDriverError(
            "configuration_missing",
            f"No Composio connected account for '{toolkit_key}': set {account_env}.",
        )
    api_key = os.environ.get("COMPOSIO_API_KEY")
    if not api_key:
        raise ToolDriverError(
            "configuration_missing", "COMPOSIO_API_KEY is not set."
        )
    try:
        from composio import Composio  # type: ignore  # optional dep, lazy (ADR-0137)
    except ImportError as err:
        raise ToolDriverError(
            "configuration_missing",
            "The composio SDK is not installed in this environment.",
        ) from err
    try:
        account = Composio(api_key=api_key).connected_accounts.get(connected_account_id)
    except Exception as err:  # noqa: BLE001 - convert ANY vendor/SDK error to governed
        raise ToolDriverError(
            "composio_api_error",
            f"Composio connected-account read failed for '{toolkit_key}': {err}",
        ) from err
    _assert_connected_account_active(account, toolkit_key)


# CUTOVER ITEM (owner-blocked, no live Composio): the EXACT active-status string is
# UNVERIFIED. Composio still returns the account record — with a status like INACTIVE/
# EXPIRED/INITIATED — after a grant is revoked, so checking EXISTENCE would read a dead
# connection as "Healthy" (the FR-24 expired-credential case, a fail-OPEN the track
# forbids). So default FAIL-CLOSED: only a status we affirmatively recognize as active
# passes; anything else (unknown/inactive/None) -> failed. Confirm the real value against
# a live connected account and widen this set at cutover.
_ACTIVE_ACCOUNT_STATUSES: frozenset[str] = frozenset({"ACTIVE"})


def _connected_account_status(account: Any) -> str:
    """The account's status as an upper-cased string, or '' if absent/unreadable."""
    if account is None:
        return ""
    status = getattr(account, "status", None)
    if status is None and isinstance(account, dict):
        status = account.get("status")
    return str(status or "").strip().upper()


def _assert_connected_account_active(account: Any, toolkit_key: str) -> None:
    """Fail closed unless the connected account reports an affirmatively-active status.

    An absent account, or one whose status we don't recognize as active (revoked/
    expired/inactive/unknown), is a FAULT, not a healthy read — never ``ok`` (FR-24).
    """
    if account is None:
        raise ToolDriverError(
            "composio_api_error",
            f"Composio returned no connected account for '{toolkit_key}'.",
        )
    status = _connected_account_status(account)
    if status not in _ACTIVE_ACCOUNT_STATUSES:
        raise ToolDriverError(
            "composio_api_error",
            f"Composio connected account for '{toolkit_key}' is not active "
            f"(status={status or 'unknown'}).",
        )


def require_composio_configuration() -> None:
    """Boot gate: refuse to start a tool-executing process on a broken Composio config.

    ``build_composio_driver`` is reached from ``_build_driver_selector``, which runs
    per ``boot_profile()`` — i.e. once per TURN, not once per process. So without
    this, a missing ``COMPOSIO_TOOLKIT_VERSION_*`` produced a clean boot followed by
    a first-turn crash: the ``ToolDriverError`` escapes ``register_turn`` as a raw
    exception, where dispatch expects a governed result. The runbook told operators
    to "watch for ``configuration_missing`` at boot"; this is what makes that true
    (fix wave 1, review Finding 4).

    Also fails closed on ``INTEGRATION_DRIVER=composio`` with zero
    ``*_CONNECTED_ACCOUNT_ID`` variables set (fix wave 2, review Finding 5) --
    without a connected account, ``pinned_toolkit_versions({})`` has nothing to
    check, so this case used to boot clean and then fail every single tool call.

    Called from every composition root that can execute a tool: the gateway, the
    turn worker, the background worker, and the per-profile dispatch server. No-op
    unless ``INTEGRATION_DRIVER=composio``.
    """
    if resolve_integration_driver() == "composio":
        build_composio_driver()


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
    this turn rather than eating the turn's whole budget. The timeout is the
    deadline divided by ``_ROUND_TRIPS_PER_EXECUTE`` for the same reason: the SDK
    makes three HTTP requests per ``execute``, so an undivided budget would be a
    3x-larger bound than the one NFR-8 states.
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
            timeout=deadline_seconds() / _ROUND_TRIPS_PER_EXECUTE,
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
        # Composio calls a VENDOR-level error a transport success: the S26 Square
        # probe returned ``successful: true`` with ``data = {"errors": [...],
        # "payment_link": null}`` (missing scope). ``successful`` and a dict ``data``
        # both pass the checks above, so without this guard a vendor fault would flow
        # to the mapper and be shaped into an all-``None`` result narrated as fact
        # (ADR-0020). Inspect both ``data`` and any nested ``response_data`` for a
        # non-empty ``errors``/``error``/``Fault`` and fail closed. Today only Square
        # emits this shape (and it is gated off), so this is latent — but it stops the
        # class at the single chokepoint both ``execute`` and the ack path route through.
        vendor_error = _vendor_error_in_payload(data)
        if vendor_error is not None:
            raise ToolDriverError(
                "composio_api_error",
                f"Composio reported a vendor error for '{action}': {vendor_error}",
            )
        return data


def _vendor_error_in_payload(data: dict[str, Any]) -> Any | None:
    """A non-empty ``errors``/``error``/``Fault`` in ``data`` or nested ``response_data``.

    Returns the offending value (for the audit message) or ``None`` when the payload
    carries no vendor-level error.
    """
    nested = data.get("response_data")
    containers = [data]
    if isinstance(nested, dict):
        containers.append(nested)
    for container in containers:
        for key in ("errors", "error", "Fault"):
            value = container.get(key)
            if value:  # non-empty list / dict / string
                return value
    return None

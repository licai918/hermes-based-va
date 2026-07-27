# QBO customer attribution via the Gadget `qboCustomerMapping` bridge

> **Status: Accepted** (decided during 0.0.4, owner decision 2026-07-22).
> Ships on `feat/0.0.4-land-all` (**S27**). S13 (QBO AR summary) builds on the
> attribution primitive this ADR governs.

## Context

Live QuickBooks invoices carry `CustomerRef.value` — a **QBO** customer id —
and **no Shopify customer id**. The pre-S27 live path
(`ComposioDriver._invoice_owned_by_verified`) attributed an invoice to a
verified Shopify customer by comparing `invoice["shopify_customer_id"]`, a
field live invoices never carry. Every comparison was `None == verified_gid`
→ False, so `toee_qbo_read.list_customer_invoices` returned an empty
**success** (`ok=True, data=[]`) to every verified customer regardless of
their real balance. The persona narrated that as fact ("you have no
outstanding invoices") — the FR-21 invented-data outcome through the
empty-success door. Proven live: an account holding invoice OL49942 for
$804.56 returned `[]`.

Attributing a QBO invoice to a Shopify customer requires an authoritative
join. The owner's Gadget app `paymentstatussync` (which syncs Shopify orders
into QBO) already persists one: the `qboCustomerMapping` model
(`qboCustomerId` ↔ `shopifyCustomerGid`, with a review `status`, plus
`matchConfidence` / `lockedByUser`).

## Decision

1. **Source of truth.** Hermes reads `qboCustomerMapping` from the
   paymentstatussync **Gadget API** — a new Hermes → owner's-app integration,
   held to the same discipline as the Composio and EasyRoutes drivers
   (env-only credentials, per-call deadline, fail-closed, total build).

2. **Trust threshold (binding).** Disclose per-customer AR only when the
   resolved mapping `status` ∈ {`CONFIRMED`, `AUTO_MATCHED`}. `NEEDS_REVIEW`,
   `REJECTED`, a missing mapping, an ambiguous set that cannot be
   disambiguated, or **any** Gadget fault/timeout → **FAIL CLOSED** (governed
   unavailable), never an empty success. On a tie between trusted mappings,
   prefer `lockedByUser`, then `CONFIRMED` over `AUTO_MATCHED`, then higher
   `matchConfidence`; a genuine tie with different values is ambiguous and
   fails closed.

3. **One primitive, two directions** (`QboAttribution`,
   `drivers/gadget.py`), which S13 also consumes:
   - `qbo_customer_id_for(verified_gid) -> str` — query by
     `shopifyCustomerGid`, apply the trust rule, return the QBO customer id.
     Used to scope **listing** a customer's invoices / AR.
   - `invoice_owned_by(qbo_customer_id, verified_gid) -> bool` — query by
     `qboCustomerId`, apply the trust rule, compare the mapping's
     `shopifyCustomerGid` to the verified GID. Used to scope a **single**
     response.

4. **Mock vs live split.** The ownership check attributes an invoice by
   **direct** Shopify linkage when the invoice carries `shopify_customer_id`
   (mock / recorded / eval invoices, which set it) — a pure comparison, no
   Gadget call — and falls back to the Gadget join only for live invoices
   that lack it. The mock QBO driver is unchanged and stays parity-correct.

5. **No hard boot gate.** The Gadget key is a separate, owner-blocked
   credential (like the EasyRoutes token). A missing `GADGET_API_KEY` makes
   QBO customer-scoped reads fail closed **per call**; it must not block the
   process from serving Shopify/Square/etc. `gadget_configured()` and
   `QboAttribution.health()` expose the signal/probe for S15/S16.

## Consequences

- `list_customer_invoices` and `get_invoice` on the live backend now fail
  closed (governed unavailable) whenever they cannot **positively** attribute
  — the empty-success door is closed. An empty list is returned only after
  the verified customer's QBO id is positively resolved.
- Until the owner provisions the Gadget API key **and** grants an API-key
  role `read` on `qboCustomerMapping`, live QBO customer-scoped reads fail
  closed. This is the intended owner-blocked posture, not a regression.
- **Coupling ceiling (`ponytail`).** Hermes reads the app's *internal*
  `qboCustomerMapping` model directly; if the app renames or reshapes it,
  attribution breaks. **Upgrade path:** the owner exposes a purpose-built,
  stable read endpoint (a Gadget action/route returning
  `{qboCustomerId, shopifyCustomerGid, status}`) and Hermes points at it
  instead of the raw model API.
- **UNVERIFIED pending the owner's key.** The mapping *field* names are
  confirmed from the app's `schema.gadget.ts` and the filter shape from the
  app's own `api.qboCustomerMapping.findMany` calls. The GraphQL endpoint
  path, auth header, read-connection name/envelope, and whether an external
  API key is granted `read` on the model are UNVERIFIED and isolated to
  `_HttpGadgetClient`; they fail closed if a guess is wrong.

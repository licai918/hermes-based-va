# toee_shopify_read v1 actions with profile-aware field gating

`toee_shopify_read` exposes four v1 **Domain Adapter Tool Action** values:

| Action | Purpose | Unmatched caller | Verified customer |
|--------|---------|------------------|-------------------|
| `get_order` | Read one order by order number or id for the matched customer | Blocked | Allowed |
| `list_customer_orders` | Read recent customer orders for **Prior Order Product Reference** | Blocked | Allowed |
| `search_products` | Search public catalog products | Allowed; public fields only | Allowed |
| `get_product` | Read one product for **Product Media Reply** | Allowed; media/link only, no account-scoped price or inventory | Allowed; may include live price and inventory |

**Tool Gate** enforces action access and response-field shaping inside the adapter. **Unmatched Caller** traffic must not receive account-scoped order facts through `get_order` or `list_customer_orders`. `get_product` and `search_products` must strip live price, inventory, and customer-specific pricing for unmatched callers even if the model requests them.

**Considered options:** merge `search_products` and `get_product` into one resolver action (rejected—harder gates for media-only unmatched replies); add `get_customer` profile reads in v1 (rejected—order and product actions cover Text-First Launch scenarios); allow unmatched `get_order` with order-number-only lookup (rejected—order lookup is account-scoped).

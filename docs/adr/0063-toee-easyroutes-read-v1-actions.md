# toee_easyroutes_read v1 actions for verified delivery lookups

`toee_easyroutes_read` exposes two v1 **Domain Adapter Tool Action** values:

| Action | Purpose |
|--------|---------|
| `get_delivery_status` | Read delivery status for a matched customer order, such as scheduled, in transit, delivered, or exception |
| `get_route_details` | Read route or stop-level details for a matched customer order, such as stop sequence, ETA, or driver route context |

Both actions require a **Verified Customer** and an order reference tied to that customer. **Unmatched Caller** traffic cannot call either action. Route changes, rescheduling, and driver assignment are out of scope in v1.

If EasyRoutes is unavailable or no route record exists, the adapter returns a governed tool-unavailable result rather than fabricated delivery facts.

**Considered options:** one combined delivery action only (rejected—route detail reads are a separate escalation step); add `list_customer_deliveries` in v1 (rejected—not needed for first launch scenarios); allow unmatched order-number-only delivery lookup (rejected—delivery is account-scoped).

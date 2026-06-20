# toee_qbo_read v1 actions with verified and email-link gating

`toee_qbo_read` exposes three v1 **Domain Adapter Tool Action** values:

| Action | Purpose |
|--------|---------|
| `get_invoice` | Read one QBO invoice by invoice number or id |
| `list_customer_invoices` | Read open or recent invoices for the matched **QBO Customer** |
| `get_ar_summary` | Read balance and AR aging summary for the matched **QBO Customer** |

All `toee_qbo_read` actions require a **Verified Customer** and a successful **Customer Email Link** between the matched **Shopify Customer** and **QBO Customer**. On **Email Link Failure**, the adapter blocks the action and returns a governed failure result for **Follow-up Case** handling rather than partial accounting disclosure.

Accounting writes, credits, refunds, and invoice adjustments are out of scope for this tool in v1.

**Considered options:** merge invoice list and AR summary into one `get_customer_ar` action (rejected—less clear eval coverage); add payment-history reads in v1 (rejected—not required for Text-First Launch scenarios); allow QBO reads without email-link gating (rejected—violates cross-system identity rules).

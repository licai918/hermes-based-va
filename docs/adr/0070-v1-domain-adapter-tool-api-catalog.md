# v1 Domain Adapter Tool API master catalog

All Toee Tire **Domain Adapter Tools** use one tool per integration with fixed v1 `action` enums per ADR-0059.

## External Customer Service Profile

| Tool | v1 actions |
|------|------------|
| `toee_identity_lookup` | `match_phone`, `match_email_sender`, `get_email_link_status` |
| `toee_knowledge_search` | `search_public_site`, `search_operational_policy` |
| `toee_shopify_read` | `get_order`, `list_customer_orders`, `search_products`, `get_product` |
| `toee_qbo_read` | `get_invoice`, `list_customer_invoices`, `get_ar_summary` |
| `toee_easyroutes_read` | `get_delivery_status`, `get_route_details` |
| `toee_square_payment_link` | `send_payment_link` |
| `toee_textline_reply` | `send_message` |
| `toee_case` | `create_case`, `update_case` |
| `toee_customer_memory` | `upsert_preference` |

## Internal Copilot Profile

| Tool | v1 actions |
|------|------------|
| Inherited external reads | `toee_knowledge_search`, `toee_shopify_read`, `toee_qbo_read`, `toee_easyroutes_read`, `toee_identity_lookup` |
| `toee_case_manage` | `claim_case`, `assign_case`, `update_priority`, `update_contact_reason`, `resolve_case` |
| `toee_copilot_draft` | `draft_sms`, `draft_email`, `draft_internal_note` |
| `toee_workbench_read` | `get_case`, `list_cases`, `get_audit_log`, `get_thread` |
| `toee_customer_memory` | `upsert_preference`, `clear_preference`, `get_preferences` |

## Supervisor Admin Profile

| Tool | v1 actions |
|------|------------|
| `toee_knowledge_ops` | `get_policy_slots`, `update_policy_slot`, `submit_for_eval`, `rollback_published_policy` |
| `toee_eval_review` | `list_eval_runs`, `get_eval_run`, `sign_off_medium_failure`, `promote_pending_policy` |
| `toee_workbench_admin` | `list_accounts`, `create_account`, `update_account_role`, `disable_account` |
| `toee_workbench_read` | `get_case`, `list_cases`, `get_audit_log`, `get_thread` |
| `toee_knowledge_search` | `search_public_site`, `search_operational_policy` |

Deferred past v1: business write tools, autonomous Copilot customer sends except approved governed-write phases, email send tool, and additional action enums without ADR approval.

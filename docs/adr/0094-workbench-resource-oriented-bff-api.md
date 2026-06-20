# Workbench resource-oriented BFF API namespaces

`apps/workbench` exposes resource-oriented BFF routes under `app/api/`. Browser clients do not call `services/hermes-gateway` directly and do not send raw `{ tool, action }` envelopes in v1.

BFF handlers validate the HttpOnly session, derive `activeProfile` from the route prefix per ADR-0093, enforce role checks, and call `packages/domain-adapters` using the v1 tool catalog from ADR-0070.

## `/api/auth`

| Route | Purpose |
|-------|---------|
| `POST /api/auth/login` | Username and password login |
| `POST /api/auth/logout` | End session |
| `GET /api/auth/session` | Return current account and role |

## `/api/copilot`

Maps to the **Internal Copilot Profile**.

| Route | Purpose |
|-------|---------|
| `GET /api/copilot/cases` | List workbench cases and filters |
| `GET /api/copilot/cases/[id]` | Read one case |
| `POST /api/copilot/cases/[id]/claim` | `claim_case` |
| `POST /api/copilot/cases/[id]/assign` | `assign_case` |
| `POST /api/copilot/cases/[id]/resolve` | `resolve_case` |
| `POST /api/copilot/cases/[id]/priority` | `update_priority` |
| `POST /api/copilot/cases/[id]/contact-reason` | `update_contact_reason` |
| `GET /api/copilot/cases/[id]/thread` | Read **Case Thread Context** |
| `GET /api/copilot/cases/[id]/audit-log` | Case audit evidence |
| `GET /api/copilot/audit/auto-handled` | Auto-handled audit list |
| `GET /api/copilot/audit/sales-outreach` | Sales outreach audit list |
| `POST /api/copilot/chat` | **Copilot Gateway** conversation with Hermes |
| `POST /api/copilot/drafts/sms` | `draft_sms` |
| `POST /api/copilot/drafts/email` | `draft_email` |
| `POST /api/copilot/drafts/note` | `draft_internal_note` |
| `POST /api/copilot/messages/textline/send` | Phase 1 governed Textline send |

## `/api/admin`

Maps to the **Supervisor Admin Profile**.

| Route | Purpose |
|-------|---------|
| `GET /api/admin/knowledge/slots` | `get_policy_slots` |
| `PUT /api/admin/knowledge/slots/[id]` | `update_policy_slot` |
| `POST /api/admin/knowledge/slots/[id]/submit` | `submit_for_eval` |
| `POST /api/admin/knowledge/slots/[id]/rollback` | `rollback_published_policy` |
| `GET /api/admin/eval/runs` | `list_eval_runs` |
| `GET /api/admin/eval/runs/[id]` | `get_eval_run` |
| `POST /api/admin/eval/runs/[id]/sign-off` | `sign_off_medium_failure` |
| `POST /api/admin/eval/runs/[id]/promote` | `promote_pending_policy` |
| `GET /api/admin/accounts` | `list_accounts` |
| `POST /api/admin/accounts` | `create_account` |
| `PATCH /api/admin/accounts/[id]/role` | `update_account_role` |
| `POST /api/admin/accounts/[id]/disable` | `disable_account` |

BFF routes remain thin orchestration layers. Business rules and tool-gate enforcement live in `packages/domain-adapters` and Hermes profile allowlists.

**Considered options:** generic `/api/*/tools` proxy (rejected—exposes raw tool surface to the browser and weakens route-level authorization); browser-direct calls to `services/hermes-gateway` (rejected—blurs employee and channel ingress boundaries); GraphQL BFF in v1 (rejected—unnecessary complexity for a small internal UI).

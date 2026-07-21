# Provider-neutral SMS naming: toee_textline_reply → toee_sms_reply

> **Status: Accepted** (2026-07-21). Completes the Textline retirement started by
> the SimpleTexting migration (commit `079f878`): the provider integration moved
> first with internal names deliberately kept to limit that diff; this ADR renames
> the internal identifiers so no live code references the cancelled provider.

## Context

Textline was cancelled and the SMS channel moved to SimpleTexting (API v2).
After the provider migration, the governed customer-send tool was still named
`toee_textline_reply`, and Textline appeared in the datastore action name, the
audit action, the workbench governed-send surface, the persisted thread-key
namespace, and the shared TS channel/provider ids. Tool names are model-facing
(persona, allowlists, Tool Gate) and provider churn should not rename them again.

## Decision

Rename to provider-neutral names where the concept is the SMS channel, and to
`simpletexting` only where the value identifies the actual provider:

| Before | After | Kind |
|--------|-------|------|
| `toee_textline_reply` (tool) | `toee_sms_reply` | model-facing tool name |
| `TEXTLINE_REPLY_TOOL` (turn-binding gate) | `SMS_REPLY_TOOL` | constant |
| `toee_case_manage.send_textline_message` | `send_sms_message` | datastore action |
| audit action `textline_send` | `sms_send` | audit row action |
| `customer_thread:textline:{phone}` | `customer_thread:sms:{phone}` | persisted thread key |
| mock `drivers/mock/textline.py` / `mock/textline.ts` | `sms_reply.py` / `sms-reply.ts` | mock modules + symbols |
| workbench `/api/copilot/messages/textline/send` | `/api/copilot/messages/sms/send` | BFF route |
| workbench `sendTextline`/`handleTextlineSend*`/`canSendViaTextline` | `sendSms`/`handleSmsSend*`/`canSendViaSms` | BFF/client/UI |
| UI "Send via Textline" | "Send via SMS" | employee-facing copy |
| TS `ChannelId "textline_sms"` / `ProviderId "textline"` | `"simpletexting_sms"` / `"simpletexting"` | provider-identifying |
| eval scenario `channel: textline` | `channel: simpletexting` | fixture data |

Python canonical event literals (`channel="simpletexting_sms"`,
`provider="simpletexting"`) were already migrated with the provider.

## Back-compat considered

- **Postgres audit rows**: existing rows keep `action='textline_send'`. Audit is
  an append-only history; nothing filters on that action name, so no data
  migration. New rows write `sms_send`.
- **Thread-key namespace** (`customer_thread:sms:`): renamed *now* because zero
  production data exists (the gateway Cloud Run service was never deployed).
  Local dev databases will start fresh threads for known phones; acceptable
  dev-only discontinuity. After production launch this key must be treated as
  frozen.
- **Eval replay**: recorded transcripts embed no tool names or channel values —
  verified by grep before the rename; the replay gate passes unchanged.
- **Not renamed**: historical ADRs/PRDs (immutable records), the dead
  `services/hermes-gateway` TS stub (superseded by ADR-0139; delete wholesale
  instead of grooming), and Composio/Twilio references unrelated to the SMS
  channel tool.

## Verification

- `hermes` pytest: 425 passed; `hermes-runtime` pytest: 339 passed.
- Root vitest (packages + workbench): 83 files / 726 tests passed.
- `eval_runner --suite text_first_launch --harness replay`: 26/26,
  `failed_high=0`.

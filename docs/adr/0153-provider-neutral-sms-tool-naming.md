# Provider-neutral SMS naming: toee_textline_reply → toee_sms_reply

> ADR number: originally drafted as 0149; renumbered to 0153 on merge because
> 0.0.3 landed ADR-0149..0152 on main first.

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
- **Not renamed**: historical ADRs/PRDs (immutable records) and Composio/Twilio
  references unrelated to the SMS channel tool.
- **`services/hermes-gateway`**: the first draft of this ADR exempted the dead TS
  stub. That was wrong — the stub *imports* `ChannelId`/`ProviderId` from
  `@toee/shared`, so renaming the shared type broke its compile and turned the CI
  `pnpm -r typecheck` job red. A dead module that still participates in the
  workspace typecheck cannot be exempted. Its two literals were updated. Its
  `verify-textline.ts` still models an HMAC body-signature scheme SimpleTexting
  does not have; deleting the stub outright is the recommended follow-up.

## Review follow-ups folded in

Review of the migration surfaced defects that this ADR's changes made reachable or
that the migration introduced. Fixed here rather than deferred:

| Issue | Resolution |
|---|---|
| The webhook token is a credential in a URL, and uvicorn logs the query string verbatim (Cloud Logging is readable far more widely than the Secret Manager grant) | `hermes_runtime/access_log.py` masks `token=` on the `uvicorn.access` logger; installed by `build_gateway_app`. The token **cannot** move to a header: SimpleTexting's webhook API accepts only `{url, triggers, requestPerSecLimit, accountPhone, contactPhone}`. **Partial by construction** — Cloud Run's own request log records `httpRequest.requestUrl` outside this logger, as does any fronting proxy, so the registered URL stays a live credential wherever request logs are readable |
| A replayed opt-out sent one real SMS per replay — the opt-out branch persists no context, so `is_duplicate` never saw it, and rate limiting deliberately runs after opt-out | New `claim_event` compare-and-set on the store (`inbound_event_claim` table, migration 0011); the confirmation is now at-most-once per `messageId`, matching the ADR-0016 invariant the pipeline comment already claimed |
| Replay protection absent in the documented deploy: the runbook never set `TOOL_BACKEND=datastore`, so production would dedup in a per-process dict across autoscaled instances | `build_gateway_app` refuses to boot the in-memory store when `DEPLOY_ENVIRONMENT` is a deployed value; the runbook now sets both vars |
| Non-UTF-8 body raised `UnicodeDecodeError` **before** the auth gate → unauthenticated 500 + traceback | Decode failure is treated as an unparseable payload; the token check still decides the response |
| `hmac.compare_digest` on `str` raises `TypeError` for non-ASCII tokens → 500 instead of 401 (and the provider retries 5xx) | Compare as UTF-8 bytes |
| `urlopen` had no timeout (a hung provider blocks the turn's dispatch thread forever) and only `HTTPError` was caught, so `URLError` escaped a sender documented to raise `SimpleTextingSendError` | 15s socket timeout; `URLError`/`OSError` converted to `SimpleTextingSendError` |
| `SOUL.md` — the model-facing response policy — still told the agent it works "SMS via Textline" | Reworded; `test_profile_soul_names_no_retired_vendor` now guards every profile prompt |

## Verification

Run **all five**. The first draft of this ADR listed only pytest, vitest, and the
eval replay — which is exactly how a compile break reached CI: vitest does not
typecheck, and the stub's own test asserted the pre-rename values, so it stayed
green while `tsc` failed.

| Gate | Result |
|---|---|
| `pnpm -r typecheck` (the CI `node` job) | Done, 6/6 workspaces |
| `hermes` pytest | 429 passed |
| `hermes-runtime` pytest | 353 passed |
| root `pnpm test` (vitest) | 83 files / 726 tests passed |
| `eval_runner --suite text_first_launch --harness replay` | 26/26, `failed_high=0` |

Note on gate strength: the eval replay does **not** validate tool naming. The only
scenario referencing the tool (`12-prior-order-ambiguous-product.yaml`) uses a
`forbidden_tools` assertion, which passes whether or not the name matches reality,
and recorded transcripts contain no sms-reply call. The `channel:` field is not
validated against any allow-list either. Real coverage for both lives in the unit
tests (`test_tool_catalog.py`, `test_gate_turn_binding.py`).

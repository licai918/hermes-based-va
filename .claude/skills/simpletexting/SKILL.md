---
name: simpletexting
description: Use when integrating with the SimpleTexting SMS API v2 — sending SMS/MMS, creating or debugging webhooks, receiving INCOMING_MESSAGE reports, contact/list management, or when code touches api-app2.simpletexting.com, SIMPLETEXTING_* env vars, or the /webhooks/simpletexting gateway route.
---

# SimpleTexting API v2

## Overview

SimpleTexting is this project's SMS provider (replaced Textline, 2026-07). REST API,
bearer auth, JSON. **It has no conversation resource** — a "conversation" is just the
contact's phone number — and **it does not sign webhooks**, so authenticity must be a
secret token embedded in the webhook URL you register.

- Base URL: `https://api-app2.simpletexting.com/v2`
- Auth: `Authorization: Bearer <API token>` on every request
- POST bodies: `Content-Type: application/json` required
- API access is by approval; token lives under Settings → API in the dashboard
- Full spec: [reference.md](reference.md) (extracted from the official OpenAPI doc)

## Quick reference

| Task | Call |
|------|------|
| Send SMS/MMS | `POST /api/messages` `{"contactPhone","text","mode"}` → 201 `{"id","credits"}` |
| Verify token/account | `GET /api/tenant` → `{"email"}` |
| List sending numbers | `GET /api/phones` |
| Create webhook | `POST /api/webhooks` `{"url","triggers":["INCOMING_MESSAGE"],"requestPerSecLimit":10}` → 201 `{"id"}` |
| List / delete webhooks | `GET /api/webhooks` / `DELETE /api/webhooks/{webhookId}` |
| Message history | `GET /api/messages` (paged) |
| Unsubscribe status | webhook trigger `UNSUBSCRIBE_REPORT` |

Send example:

```bash
curl -X POST "https://api-app2.simpletexting.com/v2/api/messages" \
  -H "Authorization: Bearer $SIMPLETEXTING_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"contactPhone": "17786803250", "text": "Hello!", "mode": "AUTO"}'
```

## Best practices (project conventions)

1. **Phones are bare digits on the wire** (`17786803250`), E.164 (`+17786803250`)
   inside our system. Strip non-digits before calling the API; `normalize_e164`
   when ingesting webhook payloads.
2. **`mode: "AUTO"`** unless you have a reason: it picks SMS / EXTENDED_SMS / MMS
   from content. `SINGLE_SMS_STRICTLY` errors on >160 chars; use it only when a
   single segment is a hard requirement. `MMS_PREFERRED` sends MMS (with
   `mediaItems`/`subject`) and falls back to SMS when the carrier can't take MMS —
   use it when attaching media.
3. **Webhook auth = URL token.** Register
   `https://<host>/webhooks/simpletexting?token=<SIMPLETEXTING_WEBHOOK_TOKEN>` and
   compare the token constant-time (`hmac.compare_digest`), fail-closed 401.
   Never register a bare URL — anyone could forge inbound traffic.
4. **Dedup on `values.messageId`**, not `reportId` — messageId is stable across
   webhook redeliveries; that's the replay protection (there is no signature/timestamp
   scheme).
5. **One webhook, many triggers.** A registration can carry several triggers;
   filter on `type` and only act on `INCOMING_MESSAGE` — ack everything else 200.
6. **`accountPhone` optional** on sends; omit to use the account's primary number.
   Set `SIMPLETEXTING_ACCOUNT_PHONE` only when the account has multiple numbers.
7. **Non-2xx must raise**, never be swallowed: a dropped customer reply is a
   silent failure. 201 is the success status for sends.
8. **Third-party link shorteners (bit.ly etc.) are rewritten** by SimpleTexting's
   own shortener (+20 chars). Don't pre-shorten links.
9. **MMS `mediaItems` in webhooks are IDs, not URLs** — `GET /api/mediaitems/{id}`
   returns metadata including a `link` field; download the actual file from that
   `link`.

## Incoming webhook payload (INCOMING_MESSAGE)

SimpleTexting POSTs this to your registered URL:

```json
{
  "reportId": "507f191e810c19729de860ea",
  "webhookId": "507f191e810c19729de860ea",
  "type": "INCOMING_MESSAGE",
  "values": {
    "messageId": "507f191e810c19729de860ea",
    "text": "Hello! How are you?",
    "accountPhone": "9053378266",
    "contactPhone": "7786803250",
    "timestamp": "2026-04-28T23:20:08.489Z",
    "category": "SMS",
    "mediaItems": ["507f1f77bcf86cd799439011"]
  }
}
```

Triggers: `INCOMING_MESSAGE`, `OUTGOING_MESSAGE`, `DELIVERY_REPORT`,
`NON_DELIVERED_REPORT`, `UNSUBSCRIBE_REPORT`. Delivery reports have no `text`;
they carry `messageId`/`carrier` instead (see [reference.md](reference.md)).

## Where this lives in the repo

| Concern | File |
|---------|------|
| Outbound sender (`ReplySender`) | `hermes-runtime/hermes_runtime/simpletexting_reply.py` |
| Webhook route + payload parse | `hermes-runtime/hermes_runtime/gateway_app.py` (`/webhooks/simpletexting`) |
| Token verify (constant-time) | `hermes/toee_hermes/gateway/verify.py` |
| Canonical event normalization | `hermes/toee_hermes/gateway/normalize.py` (`channel="simpletexting_sms"`) |
| Env catalog | `.env.example` (`SIMPLETEXTING_API_TOKEN`, `SIMPLETEXTING_WEBHOOK_TOKEN`, `SIMPLETEXTING_ACCOUNT_PHONE`, `SIMPLETEXTING_API_BASE_URL`) |
| Local webhook simulation | `scripts/simulate-simpletexting-webhook.ps1` |
| Deploy + webhook registration | `docs/ops/deploy-cloud-run.md` |

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Sending `contactPhone` with `+` prefix | Strip to digits; the API expects `1234567890` style |
| Expecting a webhook signature header | There is none — use the URL token + messageId dedup |
| Deduping on `reportId` | Use `values.messageId` (stable across redeliveries) |
| Treating every webhook POST as inbound SMS | Check `type == "INCOMING_MESSAGE"` first |
| Expecting media URLs in webhook `mediaItems` | They're IDs; `GET /api/mediaitems/{id}` |
| Retrying a 429 in a tight loop | `requestPerSecLimit` on the webhook is ≤25/s; back off |
| Omitting `requestPerSecLimit` on webhook create | Spec marks it optional but the API returns 409 `"requestPerSecLimit: must be greater than 0"` — always pass it (1–25), verified live 2026-07-21 |

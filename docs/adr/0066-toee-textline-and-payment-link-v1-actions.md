# toee_textline_reply and toee_square_payment_link v1 actions

> **Superseded in part (2026-07-21).** Textline is retired and `toee_textline_reply` is
> renamed `toee_sms_reply`; its action and **Tool Gate** rules carry over under that name.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).

## toee_textline_reply

`toee_textline_reply` exposes one v1 action:

| Action | Purpose |
|--------|---------|
| `send_message` | Send a Textline reply in the current authenticated **SMS Session**, with `body` text and optional `media_url` for **Product Media Reply** |

**Tool Gate** rules:

- Reply must stay in the current Textline thread for the verified or unmatched inbound phone session
- **Product Media Reply** may use `media_url` for public-catalog media; unmatched callers must not receive account-scoped price or inventory text in `body`
- Alternate phone numbers or emails supplied in message content do not change the send target

## toee_square_payment_link

`toee_square_payment_link` exposes one v1 action:

| Action | Purpose |
|--------|---------|
| `send_payment_link` | Create and send a Square **Payment Link** in the current verified Textline thread for a matched invoice or order reference |

**Tool Gate** rules:

- Requires **Verified Customer**
- Send target must be the current authenticated Textline thread **Registered Phone**
- Verbal or text requests to send to a new contact create a **Follow-up Case** instead of calling the tool
- Hermes confirms company, invoice or order reference, and amount before send and audits the action

In v1, autonomous customer sends use these tools on the **External Customer Service Profile**. Phase 1 **Copilot Governed Write** may call the same tools only inside an active **Human Intervention Case** with employee confirmation and stricter role checks.

**Considered options:** separate `send_text` and `send_product_media` actions (rejected—one send surface is enough for v1); split payment-link creation and send (rejected—Square flow is one governed customer action); allow payment-link send from Copilot without case linkage in v1 (rejected—weak accountability).

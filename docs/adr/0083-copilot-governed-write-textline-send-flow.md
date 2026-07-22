# Copilot Governed Write phase 1 Textline send confirmation flow

> **Provider retired (2026-07-21).** The Textline names below — the tool, the BFF route,
> and the "Send via Textline" button — are provider-neutral now; the flow itself stands.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).

Phase 1 **Copilot Governed Write** is employee-confirmed Textline send from a **Copilot Draft Action** inside an active **Human Intervention Case** tied to the current customer thread per ADR-0036.

## UI flow on `/copilot`

When an employee requests an SMS draft through **Copilot Gateway**, Hermes returns a draft card in the gateway conversation. The card contains an editable textarea with the proposed Textline body.

The employee may edit the draft inline before sending. v1 does not send SMS directly from the raw Copilot chat bubble without passing through this draft card.

Sending uses a two-step UI:

1. **Send via Textline** button on the draft card
2. A confirmation modal showing message preview, target Textline thread, case identifier, and acting **Workbench Account**

The employee must confirm in the modal before Hermes calls `toee_textline_reply.send_message` through the governed internal path.

## v1 scope and gates

- Available only for SMS **Human Intervention Case** items with an active **SMS Session** on the current thread
- Not available on audit routes, without a selected case, or for **Auto-Handled Interaction** threads
- Email cases remain `draft_email` only in v1; no governed email send button
- The case must be claimed by the signed-in **Workbench Account**, or assigned to that account by a supervisor, before send is enabled
- Send attributes the acting **Workbench Account**, passes **Tool Gate** checks, and writes **Workbench Audit Log** entries including case id, thread id, and final message body hash or text reference

Canceling the modal leaves the draft card editable and does not send.

**Considered options:** copy-only drafts with manual Textline sending at launch (rejected—user confirmed governed employee-confirmed send); one-click send without confirmation modal (rejected—weak guard against mis-send); allow governed send from audit or unselected-case gateway states (rejected—breaks case-linked accountability).

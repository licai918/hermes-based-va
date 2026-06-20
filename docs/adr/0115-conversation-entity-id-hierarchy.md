# Conversation and case entity ID hierarchy in Hermes Native Memory

> **Storage substrate superseded by ADR-0140.** The entity-id hierarchy holds; it
> is persisted in the Toee Business Datastore (Postgres), not Hermes Native
> Memory.

Tooe Tire conversation and operational records use a reference hierarchy in **Hermes Native Memory**. Cases do not own conversation threads.

## Entity hierarchy

**CustomerThread**

- one record per stable channel identity such as a Textline phone number
- long-lived container for SMS or voice-channel history in v1

**SmsSession**

- many per **CustomerThread**
- bounded by the 24-hour **SMS Session** window from ADR-0019

**MessageTurn**

- many per **SmsSession**
- one persisted turn per inbound, outbound, or Hermes message event

**FollowUpCase**

- many per **CustomerThread**
- references `customerThreadId`
- may also store the `smsSessionId` active when the case was opened

**AgentTurnContext**

- one per accepted inbound Textline `eventId`
- references `customerThreadId`, `smsSessionId`, and the persisted inbound **MessageTurn**

## Behavioral rules

**Auto-Handled Interaction** turns write **MessageTurn** records and may write **AgentTurnContext**, but do not require a **Follow-up Case**.

**Human Intervention Case** records reference the existing **CustomerThread** and are displayed through **Case Thread Context** without replacing thread storage.

Multiple cases may reference the same **CustomerThread** across time and across **SMS Session** windows. Case records do not embed the full message list.

**Considered options:** use the case record as the only conversation container (rejected—breaks auto-handled audit history and cross-case thread context); flat event-only storage without sessions (rejected—weak SMS runtime boundaries); store cases without `customerThreadId` (rejected—Copilot cannot load channel history reliably).

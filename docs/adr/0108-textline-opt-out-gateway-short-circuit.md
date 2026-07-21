# Textline opt-out keyword short-circuit in gateway pipeline

> **Provider retired (2026-07-21).** Textline was cancelled for SimpleTexting; the opt-out
> short-circuit below stands on the `/webhooks/simpletexting` pipeline.
> Superseding decision → [ADR-0153](0153-provider-neutral-sms-tool-naming.md).

SMS opt-out handling is deterministic gateway policy, not a full **External Customer Service Profile** agent turn.

## Pipeline placement

After webhook verification and normalization into `InboundChannelEvent`, the gateway checks whether the inbound body contains an **SMS Opt-Out Keyword** (`STOP`, `UNSUBSCRIBE`, or `ARRET`) before enqueueing normal agent work.

The gateway still completes **Ingress Phone Match**, writes the **Session Identity Snapshot**, and persists **AgentTurnContext** before returning `200`.

## Opt-out keyword branch

When the current inbound message is an opt-out keyword:

1. synchronously record **SMS Opt-Out** in the **Identity Graph**
2. return `200` after durable persistence
3. enqueue an `opt-out-confirm` async job instead of a normal `agent-turn` job
4. send only the brief governed confirmation reply from ADR-0016

The gateway does not invoke the full external agent for that inbound message.

## Non-keyword branch after prior opt-out

If the sender previously opted out but the current inbound message is an ordinary support request, the gateway follows the normal `agent-turn` path under **Always-On SMS Service** and governed service rules. Prior opt-out blocks marketing or proactive outbound texts only.

**Considered options:** let the external agent interpret STOP keywords (rejected—compliance behavior must be deterministic); handle opt-out before ingress or persistence (rejected—weak audit trail); block all future inbound SMS after opt-out (rejected—conflicts with ADR-0016).

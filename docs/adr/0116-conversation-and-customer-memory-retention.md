# Retention for conversation turns and Customer Memory

> **Storage substrate superseded by ADR-0140.** Retention classes hold and are
> enforced in the Toee Business Datastore (Postgres), not Hermes Native Memory.

This ADR extends ADR-0004 retention classes to conversation-layer and **Customer Memory** records in **Hermes Native Memory**.

| Data class | Retention | Notes |
|------------|-----------|-------|
| **MessageTurn** records and **CustomerThread** message bodies | 2 years | Same class as session summaries and **Follow-up Case** history |
| **AgentTurnContext** metadata | 2 years | Gateway execution metadata tied to inbound events |
| **Customer Memory** preference slots | 2 years from last channel interaction on the binding key | Any new inbound or outbound service interaction refreshes the retention window |
| **Customer Memory** merge audit metadata | 7 years | Same class as tool-call audit logs |

Customer deletion requests remain manual in the first version per ADR-0004.

**Considered options:** indefinite **Customer Memory** retention (rejected—adds unmanaged long-lived PII); 90-day retention for **MessageTurn** records (rejected—too short for service follow-up and case review); retain provisional preference copies after merge (rejected—provisional copies are removed on merge per ADR-0112).

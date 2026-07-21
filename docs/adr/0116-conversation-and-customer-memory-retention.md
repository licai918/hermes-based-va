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

## 0.0.3 S28 addendum: the orphaned-provisional retention window

This ADR's table only ever set a window for the **verified** Customer Memory
class. It didn't need to say more at the time: a **provisional** preference
copy is normally removed the moment it merges into a verified binding
(ADR-0112), so there was no separate "how long does a provisional slot live"
question to answer — merge, not aging, was assumed to be how provisional data
leaves the store.

FR-30's retention sweep (`hermes-runtime/hermes_runtime/datastore/handlers/
retention.py`) closes the gap that assumption left open: a provisional slot
that **never merges** (the customer never returns on a channel that
resolves to a verified identity) is orphaned — indefinitely live, with no
merge event ever coming to remove it, unless something else ages it out.

Decision: an orphaned provisional slot's retention window is **90 days from
its last `last_interaction_at`** (`PROVISIONAL_RETENTION_DAYS`,
`hermes/toee_hermes/drivers/mock/retention.py`) — deliberately shorter than
the verified class's 2-year window, per the same interaction-refresh rule
this ADR already sets for the verified class. Rationale: an unmerged
provisional binding carries weaker identity confidence than a verified one,
and by 90 days of silence a merge is unlikely to still happen — holding the
data longer serves no operational purpose and only extends exposure. The
number is a calibratable constant, not a schema-baked value; revisit it if
operational experience shows 90 days is too short (merges arriving later
than expected) or unnecessarily long.

# Data retention periods for Hermes customer service

Hermes applies defined retention periods by data class. The opening greeting already discloses that calls may be recorded.

| Data class | Retention | Notes |
|------------|-----------|-------|
| Call recordings | 90 days | Stored via Twilio; individual disputes may be extended manually |
| Call transcripts | 90 days | Same cycle as recordings for Copilot review |
| Session summaries and Follow-up Cases | 2 years | Supports service follow-up and quality review |
| MessageTurn records and CustomerThread message bodies | 2 years | Conversation-layer SMS and channel message history |
| AgentTurnContext metadata | 2 years | Textline gateway inbound execution metadata |
| Customer Memory preference slots | 2 years from last channel interaction | Refreshed on new service interaction for the binding key |
| Customer Memory merge audit metadata | 7 years | Provisional-to-verified merge accountability |
| Tool-call audit logs | 7 years | Covers accounting reads, Payment Link sends, and other governed actions |
| Published knowledge version history | Indefinite for published records | Supports rollback and accountability |

Customer deletion requests are handled manually in the first version; Hermes does not automatically erase data across Twilio, Hermes DB, and source systems.

**Considered options:** uniform 90-day retention for all data (rejected—insufficient for audit and case history); indefinite retention for recordings (rejected—storage cost and privacy exposure).

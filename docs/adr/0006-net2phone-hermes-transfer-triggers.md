# Net2phone Hermes transfer triggers for phone MVP

All phone routing into Hermes VA is configured by the operations department in the Net2phone admin console. Hermes does not define or enforce which calls transfer to the Twilio Hermes line.

First-version **Hermes Transfer Rules** enabled in Net2phone:

1. **After-hours routing** — calls during off-hours periods defined by operations transfer to Hermes.
2. **No-answer routing** — calls that ring through the live-staff queue without answer transfer to Hermes instead of voicemail.

First-version rules **not** enabled:

- Dedicated IVR key for “AI customer service”
- Proactive business-hours routing to Hermes ahead of live staff
- Overflow routing (optional later if live queues are routinely saturated)

Hermes handles any call that arrives on the Twilio Hermes line through the **External Customer Service Profile**. Routing trigger metadata from Net2phone may be stored for analytics and greeting selection, but Hermes does not second-guess Net2phone routing decisions.

**Considered options:** Hermes maintaining parallel routing rules (rejected—duplicate ownership); overflow as day-one requirement (deferred—keep MVP simple).

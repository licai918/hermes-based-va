# After-hours routing owned by Net2phone, not Hermes

**After-Hours Service** describes how Hermes handles phone conversations that arrive after Net2phone routes them to the Twilio Hermes line. Hermes does not define, store, or enforce the after-hours time window for call routing.

The operations department configures **After-Hours Transfer Rules** in the Net2phone admin console. When those rules apply, Net2phone automatically transfers the call to Hermes VA. Hermes assumes any call on the Twilio Hermes line is in scope for the **External Customer Service Profile** after-hours behavior (no live handoff, follow-up cases, etc.).

Hermes may still answer customer questions about published business hours from **Public Site Knowledge** or **Operational Policy Knowledge**, but that content is informational only and must not be used to decide whether a call should route to Hermes.

**Considered options:** Hermes maintaining its own business-hours schedule for routing (rejected—duplicates Net2phone and creates conflict); Twilio time-based routing as source of truth (rejected—operations already manages Net2phone).

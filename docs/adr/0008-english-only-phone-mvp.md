# English-only external phone service for MVP

The first-version **External Customer Service Profile** on phone supports English only. Twilio STT/TTS, **Opening Greeting**, **Operational Policy Knowledge**, and **Public Site Knowledge** used on phone are English.

If a caller speaks French or requests French service, Hermes politely explains that AI phone support is currently English-only, collects company name, contact details, and a short problem summary, and creates a **Follow-up Case** for human follow-up on the next business day. Hermes does not improvise French policy answers or enable a French phone knowledge path in MVP.

SMS, email, and web chat language support may be evaluated in a later phase.

**Considered options:** bilingual phone MVP (deferred—doubles TTS/STT, greeting, eval, and knowledge scope); automatic transfer to French-speaking staff (not available in after-hours/no-answer MVP).

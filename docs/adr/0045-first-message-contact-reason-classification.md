# First-message contact reason classification for external channels

When an inbound party on the **External Customer Service Profile** is not a **Verified Customer**, Hermes classifies **Contact Reason** from the first message on Textline SMS, the first spoken utterance on voice, or the first body on a later email channel using intent classification in the external turn.

Classification distinguishes **Unmatched Caller** customer-service intent from **Non-Customer Contact** purposes such as government, supplier, staffing, **Sales Outreach**, and **Named Recipient Request**. Hermes writes the result into the active session or case record before selecting response language.

If the first message is ambiguous, Hermes asks one brief neutral clarification question in English, still with zero account disclosure. Examples include distinguishing order-account help from other business matters. If intent remains unclear after that clarification, Hermes creates a **Follow-up Case** with **Contact Reason** `unknown`.

Hermes does not default ambiguous inbound traffic to **Unmatched Caller** recovery language such as **Registered Phone** guidance until customer account-service intent is established.

**Considered options:** default all non-verified inbound to **Unmatched Caller** (rejected—wrong scripts for government and supplier contacts); defer all classification to Copilot staff (rejected—poor first response); keyword-only routing without conversational intent review (rejected—too brittle for natural-language first messages).

# Separate non-customer contacts from unmatched customer callers

Inbound traffic on the **External Customer Service Profile** includes parties who are not seeking Toee Tire customer account service, such as government agencies, suppliers, and temporary workers. These must not be handled with the same scripts and case routing as an **Unmatched Caller** who is likely a customer calling from a non-registered phone.

Hermes distinguishes **Non-Customer Contact** from **Unmatched Caller** when the inbound party has no **Verified Customer** **Session Identity Snapshot**. Both categories receive zero account disclosure and may create a **Follow-up Case**, but they use different intake language, **Contact Reason** categories, and Copilot routing.

**Unmatched Caller** remains the term for a likely customer contact whose phone does not match Shopify **Registered Phone**. Hermes may still offer public-catalog help such as **Product Media Reply** and may suggest contacting from a **Registered Phone** for account access.

**Non-Customer Contact** is the term for inbound parties whose stated purpose is not customer account service, such as tax authority, supplier, staffing, or other business-to-business operational matters. Hermes does not suggest **Registered Phone** verification and routes the case to internal operational follow-up instead of customer-account recovery language.

**Considered options:** treat all non-verified inbound as **Unmatched Caller** (rejected—wrong scripts for government, supplier, and staffing contacts); skip classification and rely only on free-form Copilot tags (rejected—weak first-response quality and queue routing); create a separate Hermes Profile per party type (rejected—unnecessary channel split for v1).

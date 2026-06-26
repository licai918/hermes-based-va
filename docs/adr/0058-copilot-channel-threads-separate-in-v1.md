# Separate channel threads in Copilot for v1

In v1, the **Copilot Workbench** displays conversation context by active channel thread only. A **Human Intervention Case** opened from Textline shows **Case Thread Context** for the current **Customer Thread**; an email case shows the current **Email Thread**. Hermes does not merge SMS, email, and voice messages into one combined timeline in the default workbench UI.

The **Identity Graph** may still record cross-channel links between verified identities, phone numbers, email addresses, and business-system customer records for audit and future use. Supervisors may inspect those links through governance or audit surfaces, but **Customer Service Rep** users do not receive a cross-channel merged timeline in the first version.

**Considered options:** merge all channel history into one Copilot timeline in v1 (rejected—higher UI complexity and context noise); hide all cross-channel linkage even in **Identity Graph** (rejected—loses audit value); allow reps to open linked channel threads by default (rejected—user chose channel-separated v1 UI).

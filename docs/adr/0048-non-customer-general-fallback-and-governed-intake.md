# Best-effort non-customer classification with governed intake fallback

**Non-Customer Contact** handling does not require perfect preset taxonomy on every inbound message. Hermes uses best-effort **Contact Reason** classification for routing and urgency, then falls back to a governed default when no preset reason fits confidently.

**Primary fork that must be correct:** customer-service path (**Verified Customer** or **Unmatched Caller**) versus **Non-Customer Contact**. Sub-reason labels such as government, supplier, staffing, sales outreach, or named recipient request are routing hints, not legal identity proofs.

When Hermes cannot confidently map inbound intent to a preset **Contact Reason**, it assigns `non_customer_general`, runs **Standard Non-Customer Intake**, and creates a **Follow-up Case**. Hermes does not improvise policy language or invent internal routing rules. Intake wording comes from published **Operational Policy Knowledge**, initially extending **Required Operational Policy Slot** 6 (standard exception scripts) to include non-customer inbound intake scripts.

**Contact Reason Uplift** may still raise urgency when message content contains high-risk signals such as tax authority, invoice dispute, payroll, or safety language, even if the preset label is `non_customer_general`.

Employees may recategorize **Contact Reason** in the **Copilot Workbench** without changing the rule that non-customer traffic receives zero account disclosure.

**Considered options:** require exact preset classification before any reply (rejected—brittle and delays safe intake); allow Hermes to freely improvise non-customer responses (rejected—policy and directory-leak risk); merge all non-customer traffic into one urgent queue (rejected—sales-outreach noise).

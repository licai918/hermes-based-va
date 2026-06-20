# Non-customer contact first-response playbooks for sales and named-recipient requests

After **Contact Reason** classification on the **External Customer Service Profile**, Hermes uses different first-response playbooks for **Sales Outreach** and **Named Recipient Request** **Non-Customer Contact** traffic.

**Sales Outreach:** Hermes sends a brief professional English decline and always creates a low-priority **Follow-up Case** with **Contact Reason** `sales_outreach`. The case exists for audit sampling and supervisor review, not because Hermes expects employee drafting on every cold pitch.

**Named Recipient Request:** Hermes collects who the caller is trying to reach, the reason for contact, and a callback number or channel. Hermes creates a **Follow-up Case** with **Contact Reason** `named_recipient_request`. Hermes does not state whether the named employee is available, does not provide internal extensions, personal mobile numbers, or unlisted direct lines, and does not perform live transfer in v1.

Both playbooks preserve zero customer-account disclosure and do not use **Registered Phone** customer-recovery language.

**Considered options:** auto-handled sales decline without a case (rejected—user chose audit trail on all sales outreach); publish an employee routing directory for named-recipient calls (rejected—user chose intake-only without directory disclosure); live transfer for named-recipient requests in v1 (rejected—conflicts with no real-time handoff).

# Launch eval coverage for non-customer inbound scenarios

The **Launch Eval Gate** must include non-customer inbound scenarios before **Text-First Launch** and on subsequent material changes. These tests validate **Contact Reason** classification, **Standard Non-Customer Intake**, urgency rules, and zero-account-disclosure boundaries defined in ADR-0044 through ADR-0048.

The minimum added scenarios are government default urgent, supplier invoice uplift, sales outreach low-priority case, named recipient non-disclosure, and non-customer general governed fallback without improvised policy.

**Considered options:** rely on post-launch Copilot sampling only (rejected—first-response policy risk on government and directory leakage); test only customer scenarios (rejected—external channels receive mixed inbound traffic); add every possible contact subtype (rejected—five representative scenarios are enough for v1).

# Shared non-customer rules across SMS, voice, and later email

When an email channel is added after **Text-First Launch**, inbound email uses the same **External Customer Service Profile**, **Contact Reason** taxonomy, non-customer playbooks, urgency rules, **Sales Outreach Audit View** routing, and **Launch Eval Gate** scenarios as Textline SMS and voice.

Email differs only at the identity ingress layer. Email has no **Ingress Phone Match**; the **Channel Gateway** performs **Sender Identity Intake** from the inbound sender address, display name, and stated organization before agent processing. Non-customer classification still happens from the first message body using the same best-effort **Contact Reason** rules and **Standard Non-Customer Intake** fallback.

Email go-live requires a subsequent **Launch Eval Gate** pass that reruns the non-customer scenarios 14–18 on email fixtures, in addition to any email-specific customer-identity scenarios defined later.

**Considered options:** simplify all email non-customer traffic to `non_customer_general` only (rejected—loses government urgent and supplier uplift rules); route email to a separate non-Hermes mailbox (rejected—splits policy and audit); delay all email policy decisions until implementation (rejected—channel parity should be decided before build).

# Fixed email support signature for all outbound email

The **Email Support Signature** uses one fixed English signature line for every Hermes outbound email on the email channel. It does not vary for **Verified Customer**, **Unmatched Caller**, or **Non-Customer Contact** traffic.

Customer-specific recognition such as company name belongs in the message body when appropriate, not in the signature line. The exact signature text is governed by published **Operational Policy Knowledge** in **Required Operational Policy Slot** 6.

**Considered options:** include matched company name in the signature for verified senders (rejected—repetitive on every email and adds disclosure surface); maintain multiple signature templates by contact reason (rejected—unnecessary complexity for v1); allow Hermes to improvise signature text (rejected—policy drift risk).

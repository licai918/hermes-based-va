# Email sender match for silent customer verification on the email channel

When the email channel is added, inbound email uses **Email Sender Match** as the parallel identity step to **Ingress Phone Match** on Textline SMS and voice. During **Sender Identity Intake**, the **Channel Gateway** synchronously matches the inbound sender address against Shopify Customer email records before **Hermes Core** processes the message.

If exactly one Shopify Customer matches the sender address, Hermes treats the sender as a **Verified Customer** for that email session with the same external tool permissions as phone-verified customers. If no match is found and the intent is customer account service, Hermes treats the sender as an **Unmatched Caller**. If the intent is non-customer, Hermes uses **Non-Customer Contact** handling instead.

Customers do not receive a separate email verification ceremony. Verification is complete at message receipt when the sender address matches.

Email go-live must add **Launch Eval Gate** scenarios for verified, unmatched, and non-customer email traffic in addition to rerunning non-customer scenarios 14–18 on email fixtures.

**Considered options:** treat all inbound email as unmatched until manual review (rejected—adds friction for legitimate customer email support); require customers to verify through a separate email code flow (rejected—conflicts with silent verification); use only domain-level matching without full address match (rejected—too weak for account disclosure).

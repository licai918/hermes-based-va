# Email sender match uses authenticated From only

On the email channel, **Email Sender Match** uses only the authenticated **From** address resolved by the **Channel Gateway** after inbound mail authenticity checks. Hermes does not use **Reply-To**, body-supplied alternate addresses, or forwarded-address text for customer verification.

This parallels SMS and voice rules that reject phone numbers or emails supplied only in message content. **Payment Link**, account-scoped reads, and verified outbound replies must stay in the authenticated email thread tied to that **From** identity.

Requests to continue service on a different email address create a **Follow-up Case** rather than re-verifying against the new address in the same turn.

**Considered options:** prefer **Reply-To** over **From** (rejected—spoofing and forwarding risk); require **From** and **Reply-To** to agree before verification (rejected—legitimate business inboxes often differ); accept body-supplied alternate emails for match (rejected—same risk as verbal new-contact payment links).

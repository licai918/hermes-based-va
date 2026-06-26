# SMS Payment Link delivery on the same verified Textline thread

When a **Verified Customer** requests a **Payment Link** over Textline SMS, Hermes sends the Square link only as a reply in the **current Textline conversation thread** to the same phone number that passed **Phone Match Verification** as a Shopify **Registered Phone**.

Hermes does not send a Payment Link to a new phone number or email provided in the SMS body. Such requests create a **Follow-up Case**. Before sending, Hermes confirms company name, invoice or order reference, and amount, and audits the case, invoice or order id, and send time.

**Considered options:** sending to Shopify registered email from an SMS request (rejected for SMS-first MVP—keeps channel and verified identity aligned); sending to a verbally/textually supplied alternate contact (rejected—existing Registered Contact rule).

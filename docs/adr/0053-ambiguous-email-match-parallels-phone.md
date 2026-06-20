# Ambiguous email sender match parallels ambiguous phone match

On the email channel, **Email Sender Match** may resolve to **Ambiguous Email Match** when one inbound sender address matches more than one Shopify Customer **Registered Email** record.

Hermes records the ambiguous outcome during **Sender Identity Intake** before agent processing. Hermes does not auto-select the first matched customer and does not downgrade the sender to **Unmatched Caller** solely because multiple customers share the address.

When the sender requests account-scoped facts, Hermes asks for disambiguation such as company name, order number, or invoice number. If disambiguation fails, Hermes creates a **Follow-up Case**. Public-catalog or non-account requests may continue under zero-account-disclosure rules without treating the sender as **Verified Customer**.

**Considered options:** auto-bind the first Shopify match (rejected—wrong-customer disclosure risk); treat all multi-match senders as unmatched (rejected—over-penalizes shared company inboxes); require a separate email verification ceremony (rejected—conflicts with silent verification).

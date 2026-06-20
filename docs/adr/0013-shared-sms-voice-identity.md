# Shared phone-match verification for Textline SMS and voice

**Phone Match Verification** applies uniformly across customer-facing channels that carry a phone identity. For **Text-First Launch** on Textline SMS, the inbound sender phone number is matched against Shopify Customer **Registered Phone** using the same rules as voice.

Verified, unmatched, and ambiguous match outcomes, **Customer Email Link** behavior, **Payment Link** restrictions, and **Follow-up Case** creation are identical between SMS and voice. Hermes merges conversation history and identity context by phone number in the **Identity Graph**.

**Considered options:** stricter SMS verification (rejected—duplicates policy and adds friction); separate SMS identity store (rejected—fragments customer context).

# Shopify content gaps — fill these so the knowledge layer can answer

Surfaced by the 0.0.3 knowledge spike (27 docs pulled from the store). These are **content**
gaps, not retrieval-tech gaps — no retriever can answer what isn't written down. Filling the
HIGH items also directly lifts S-QUAL recall (some misses were pure content gaps).

Where: Shopify admin → **Online Store → Pages** (for pages) and **Settings → Policies** (for
the shop policies). All read-only-verified 2026-07-16.

---

## 🔴 HIGH — customers ask this and there's currently NO answer anywhere

- [ ] **Business hours** — *missing entirely.* The Contact page has phone / email / address
      but **no hours**, so "what are your hours / are you open now" is unanswerable today.
      → Add opening hours (days + times + timezone) for **both** locations (Oakville 447 Speers
      Rd; Cambridge 261 Hespeler Rd), plus after-hours / holiday note. Put it on the **Contact
      page** and/or the FAQ.

- [ ] **FAQ page** (`/pages/faq`) — *exists but is EMPTY.* This is the single biggest win: an
      FAQ of short Q&A is exactly what customer questions match against. Seed it with the
      answers you already have elsewhere, one Q per answer:
      - Hours (once added) · Returns (7-day, 15% restocking — already on Return Policy) ·
        Shipping (free pickup + free industrial delivery, +CAD$15 under 2 tires / residential —
        already on Shipping Options) · Warranty (already on Warranty Information) ·
        **Payment methods** (see below) · How to order / min order · Tire fitment basics ·
        How to set up an account.

- [ ] **Payment methods** — *no content found anywhere in the store's pages/policies.* "What
      payment do you take / do you offer terms" is unanswerable. → Add a short page or an FAQ
      entry (cards, e-transfer, net terms for dealers, deposits, etc.).

## 🟡 MEDIUM — exists but thin or duplicated

- [ ] **Shipping Policy** (Settings → Policies) — *EMPTY.* The **Shipping Options page** has the
      real content (pickup + free industrial delivery + $15 rule), but the formal **policy** is
      blank. → Mirror the Shipping Options text into the policy (or point to the page) so both
      agree.

- [ ] **Contact page** — has trade name / phone `905-337-8266` / email `info@toeetire.com` /
      Oakville address, but VAT & Trade number are blank and **no hours**. → Add hours (above);
      add the Cambridge location; fill or remove the blank VAT/Trade fields.

## ⚪ LOW — cleanup (dead/duplicate pages that waste retrieval + confuse)

- [ ] **"How to set up an account"** article — *EMPTY.* → Write 3–4 steps, or delete the page
      (it's currently a dead link).
- [ ] **`who-we-are`** and **`about-us-1`** pages — *EMPTY duplicates* of the real Brand Story
      (`about-us`). → Delete or redirect to `about-us` so they stop competing in search.

---

## Already good (no action — for reference)
- **Warranty Information** (6.5k chars), **Return Policy** = **Refund Policy** (identical,
  7-day / 15%), **Brand Story** (about-us), **Shipping Options page**, brand pages
  (Windforce, Grenlander), tire-education articles (sidewall numbers, winter season, etc.).

## Not a content gap (handled elsewhere — don't add to pages)
- Live prices / stock / fitment / order tracking → the Shopify product & order tools (real-time).
- The 6 governed **operational-policy slots** (business hours, payment, returns, etc.) are a
  *separate* system authored in the Workbench — filling those is a different track from these
  public-site pages.

# S24 — what the real transcript says, and what the corpus cannot answer

Source: one real SMS transcript, 8 conversations, Jul 16–28, all **B2B** (tire shops and a
roadside business ordering wholesale). Corpus compared against:
`workspace/0.0.3/knowledge-spike/probe/corpus.json` — 27 real Toee Tire docs.

## The headline: this channel is mostly NOT a knowledge channel

Counting every distinct customer intent in the transcript:

| Intent | Instances | Answerable from the L5 corpus? |
| --- | --- | --- |
| Place an order (size + qty + season) | ~10 | **No** — a transaction. Tool territory. |
| Delivery timing ("what time is your next run", "today or tomorrow") | 5 | **No** — live operational state. |
| Price ("price", "price for run-flat and regular") | 3 | **No, deliberately.** The ingest boundary check flags price-like text as `live_fact_pattern` precisely so prices are never answered from a cached corpus. |
| Payment sent / credit applied | 4 | **No** — transaction. |
| Order status / cancellation | 2 | **No** for status; **gap** for cancellation policy. |
| Return | 1 | **Yes** — `return-policy` / `REFUND_POLICY`. |
| Pickup vs delivery, billing terms | 2 | **Yes** — `shipping-options`, `tire-shop-owner-program`. |
| Website / account / order number | 2 | **Barely** — one line in `tire-shop-owner-program`. |
| Brand question | 1 | **Yes** — `grenlander`. |

**So the majority of real traffic on this channel is tool work, not retrieval.** That matters for
how FR-30's number is read: `recall@3 ≥ 80%` measures the knowledge layer against the questions
the knowledge layer is *for*. It does not measure how well the assistant handles this channel,
because most of this channel is orders, prices and ETAs. A green gate here is not a claim about
the customer experience these eight conversations represent.

That is a finding about the product, not a complaint about the metric. It suggests the highest-
value next work for this channel is the **tool** path (order placement, order status, live price),
with L5 as the smaller supporting layer.

## Real questions with no page behind them — the actual content gaps

Every one is traceable to a line in the transcript. These are **excluded from the scored set**
in `questions-real.json`, because a question with no correct page in the corpus can never be
retrieved: counting it would report a *content* problem as a *retrieval* failure and quietly drag
recall below the bar. They belong in the Shopify-edit-and-re-ingest flow S24 names.

### 1. Delivery schedule and cut-off — the most-asked question in the transcript

Five separate asks:
- "What time is your next delivery?" (C1, Jul 28 09:32)
- "If I order 4 more tires now, can I have them today or not?" (C1, 13:40)
- "are you going to send my last order today or tomorrow? **I need to schedule my day.**" (C1, 14:49)
- "Am I able to get them tomorrow?" (C8, Jul 21 12:00)
- "How long for 2 sets?" (C4, Jul 28 10:22)

`shipping-options` says delivery is free to qualifying locations. **It says nothing about when.**
No page states the daily run times, the order cut-off, or the same-day rule. A staffer answered
each of these by hand ("ETA 2:18 PM", "It will be tomorrow morning", "9:50 this morning").

Some of that is genuinely live and belongs to a tool. But the *rule* — "orders placed before X go
on the morning run" — is stable policy and is exactly what a corpus page should hold. **Highest-
value single page to author.**

### 1b. Opening hours — MOVED HERE FROM THE SCORED SET, and the rule that moved it

*"What time do you open"* was originally scored against `CONTACT_INFORMATION`. That page is, in
full: trade name, phone number, email, physical address, and two blank tax fields. **It contains no
hours of any kind.** No retrieval system can answer the question from it, so scoring it measured a
content gap as a retrieval failure.

**The rule, applied uniformly and stated before the numbers:** a question stays in the scored set
**iff its gold page contains an answer to it**. It was applied to all six remaining misses, and it
moved exactly one:

| miss | gold page contains the answer? | outcome |
| --- | --- | --- |
| `do i pay shipping if i only order one tire` | **yes** — *"if your order quantity is less than 2 … Extra CAD 15.00"* | **stays** — a real retrieval miss |
| `do you charge extra for a residential address` | **yes** — *"remote locations or residential area. Extra CAD 15.00"* | **stays** — a real retrieval miss |
| `do you sell grenlander` | **yes** — the `grenlander` page | **stays** — a real retrieval miss (rank 4) |
| `how do i log in to your website to order` | **weakly** — one clause, *"login in your account in toeetire.com"* | **stays** — the conservative call; thin content is not absent content |
| `i got damaged tires what do i do` | **yes, on a page the label omitted** | gold **widened** to include `warranty-information` |
| `what time do you open` | **no — the page has no hours at all** | **moved here** |

The same defect exists in the **synthetic interim set** (`what are your hours` → `CONTACT_INFORMATION`),
which is why this is a rule rather than special pleading for the real set: it was recorded in
GATE-REPORT.md *before* any of these corrections were made or any improved score was known.

**The honest pair of numbers is reported both ways in GATE-REPORT.md.** Removing a question because
it fails would be indefensible; removing one because its gold page provably cannot answer it is a
labelling fix — and the difference is only credible because the rule was written down first and
applied to every miss, not just the convenient one.

### 2. Where to find an order number

Verbatim: *"I can't find the order number because I don't know how to use your website update."*
(C7, Jul 25 08:28)

A customer trying to return four tires could not complete the request. `tire-shop-owner-program`
says "login in your account in toeetire.com" and nothing more. No page covers the account UI,
order history, or where an order number appears. This one blocked a real transaction.

### 3. All-season vs all-weather

*"Looking for 255/40R19 all season/weather."* (C5, Jul 27 12:34) — the customer used both terms as
if interchangeable and was quoted two different prices ($97.90 / $94.90). No corpus page explains
the difference. Every such conversation costs a manual explanation, and the two are not the same
product class.

### 4. Run-flat

*"Price for run-flat and regular."* (C6, Jul 25 12:09) — no page mentions run-flat at all.

### 5. Order cancellation

*"Other orders can cancel. OL49897."* (C1, Jul 28 15:06) — `return-policy` covers **returns after
delivery**. It says nothing about cancelling before dispatch, which is a different question with a
different answer.

### 6. Account credit

*"There is a $142.52 credit from OL48976."* (staff, C1 15:20) — credits exist and are applied
against new orders. No page explains how a credit arises, how long it lasts, or how a customer
sees their balance.

## What the transcript DOES cover well

`shipping-options`, `return-policy`/`REFUND_POLICY` and `tire-shop-owner-program` turned out to be
squarely on-target for this audience — every customer here is a registered tire business, and that
program page names Payment Terms, Discount and **Prioritized Delivery**, which is precisely what
the repeated "morning run" requests are asking for. The 22 scored questions lean on those three
plus `grenlander`, `bulk-order-discount` and `CONTACT_INFORMATION`.

## Honest count

**22 scored questions, not ~30**, and they cover **~16 distinct intents**. Every question is
traceable to a cited transcript line; none is paraphrase padding. Inflating to 30 by rewording the
same six intents would produce a set that *looks* like 30 real questions and measures six — the
exact shape of self-deception this project keeps catching elsewhere.

To reach a genuine ~30, the cheapest source is **more transcript from channels where customers ask
policy questions rather than place orders** — new-customer enquiries, warranty claims, the web
contact form, or the email channel. This transcript is a repeat-B2B ordering thread; its regulars
already know the policies and only ask about today's truck.

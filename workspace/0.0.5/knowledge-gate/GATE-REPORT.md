# S24 gate run — 2026-07-28

Corpus ingested fresh: **167 chunks from 27 docs** (matches the spike's proven figure).
Boundary check flagged 7 chunks `live_fact_pattern` (CAD 15.00, CAD 2,000, $500/$1000 coupon
amounts) — flagged for review, still indexed, which is the designed behaviour.

| Question set | recall@3 | Bar 80% |
| --- | --- | --- |
| Synthetic (interim, 30 q) | **22/30 = 73%** | FAIL |
| **Real — owner transcript (22 q)** | **13/22 = 59%** | FAIL |

**The bar was not met and is not being lowered.** S24's own approach says so: *"If the bar cannot
be met after content fixes, the honest outcome is a documented gap-analysis + owner decision —
never a silently lowered bar."*

## The finding that matters more than the number

**The real set scores 14 points WORSE than the synthetic one, and the reason is vocabulary.**

Three of my questions have near-twins in the synthetic set. The twins hit; mine missed:

| Synthetic (hit) | Real, from the transcript (miss) |
| --- | --- |
| "do you deliver or do i have to **pick them up**" | "do you deliver or do i have to **come get them**" |
| "do you **carry** windforce" | "do you **sell** grenlander" |
| "do you give a discount if i buy **a lot at once**" | "do i get a better price if i take a **bigger lot**" |

The synthetic set was written by someone who had **read the corpus**. Its phrasing echoes the
pages. Real customers use trade vocabulary the pages do not contain — *come get*, *sell*, *lot*,
*bill me out*, *2 sets*.

**So the interim 73% was inflated by its own authorship, and 59% is the honest baseline.** That is
not a criticism of whoever wrote the synthetic set — an interim set has to come from somewhere —
but it means the "73% → 80%" gap was always understated, and any trend line drawn between the two
sets is comparing different difficulties.

## A second flaw in the measurement itself

`recall@3` scores a HIT when the gold **page** appears in the top 3. It does not check that the
page **answers**.

Concrete case: the synthetic set labels *"what are your hours"* → `CONTACT_INFORMATION`. That page
contains trade name, phone, email, physical address and two blank tax fields. **It contains no
opening hours.** If that question hits, it hits by retrieving a page that cannot answer it.

My own transcript-derived "what time do you open" carried the same gold and missed — so the real
set is *penalised* for a question the synthetic set can score on while being equally unanswerable.

**This should be fixed before the number is signed off**, and it is a labelling fix, not a
retrieval fix: a gold label should only name a page that actually contains the answer.

## The nine misses, classified as S24's approach requires

### Vocabulary / normalization gap — 4

The page exists and answers the question; the customer's words do not reach it.

1. `do you deliver or do i have to come get them` → got `reward-discount`, `2024-winter`, `tire-shop-owner-program`
2. `do i pay shipping if i only order one tire` → got `bulk-order-discount` ×2, `reward-discount` (the target chunk literally says *"if your order quantity is less than 2 … Extra CAD 15.00"*)
3. `do you sell grenlander` → got `in-the-fog`, `2024-winter` ×2 (there **is** a `grenlander` page)
4. `do i get a better price if i take a bigger lot` → got `2024-winter`, `5-reasons-to-buy`, `reward-discount`

**This is what L7 is for.** The lexicon already holds tire-size normalizers; these are the same
mechanism applied to **trade synonyms**: `come get` / `collect` → `pick up`; `sell` / `stock` →
`carry`; `lot` / `set` → `bulk`. Four of nine misses — **44% of the failure** — sit in exactly the
layer 0.0.5 built. Worth proposing as confirmed `alias` entries and re-measuring; that is the
with/without L7 synergy measurement S24 asks for, and it now has a real target rather than a
synthetic one.

### Retrieval gap, content present — 2

5. `do you charge extra for a residential address` → got `PRIVACY_POLICY` ×2, `TERMS_OF_SERVICE`.
   Striking: the word *residential* is **in the target chunk** (*"a location that does not qualify
   … particularly remote locations or residential area"*). "Address" appears to pull the query
   toward privacy/personal-information content strongly enough to bury an exact term match. Worth
   a look at the hybrid weighting — this is the clearest single case for tuning.
6. `can you bill me and i pay when i pick up` → got `TERMS_OF_SERVICE`, `return-policy`,
   `REFUND_POLICY`. `tire-shop-owner-program` lists "Payment Terms" as a **two-word bullet** with
   no surrounding text. Thin content, not a retrieval bug — closer to a content gap.

### Content gap, page genuinely silent — 2

7. `how do i log in to your website to order` — predicted in CONTENT-GAPS.md and confirmed. The
   only login text in the whole corpus is one clause: *"login in your account in toeetire.com"*.
8. `what time do you open` — `CONTACT_INFORMATION` has no hours (see above).

### My own labelling error — 1

9. `i got damaged tires what do i do` → got `warranty-information` ×3, gold was
   `return-policy`/`REFUND_POLICY`. **The retriever was right and my label was too narrow.**
   Damaged tires → warranty is a correct source. Recording it here rather than quietly widening
   the gold, because widening a label after seeing the result is how a gate gets talked into
   passing. If the owner agrees `warranty-information` belongs in that question's gold, the
   corrected score is **14/22 = 64%** — still a fail.

## What would actually close the gap

In descending value:

1. **Author the delivery-schedule page** (CONTENT-GAPS.md item 1) — the most-asked question in the
   entire transcript has no page at all, and it is not even in the scored set because of that.
2. **Seed the trade synonyms into L7** — four scored misses, zero new content required.
3. **Fix the gold labels that name pages which cannot answer** — in both sets.
4. **Add hours to `CONTACT_INFORMATION` and a login/order-number page** — two content gaps, small.
5. Only then look at retrieval tuning, with `residential address` as the test case.

None of that is a bar change.

# S24 gate — FINAL, 2026-07-29

> **Result: 17/21 = 81% PASS (exit 0)** on the corrected set, **17/22 = 77% FAIL** if the one moved
> question is kept. Both numbers are real and the owner should see both — the pass is by less than
> one question. What changed, and why each change is defensible, is in the section
> *"Closing the gap"* at the end. The original review-time analysis below is kept unedited, because
> the rule that moved a question was written down in it **before** any improved score existed.

---

# S24 gate run — 2026-07-28 (review-time analysis, unedited)

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

## The L7 synergy, measured — and the wiring that does not exist

**S24's brief assumes a synergy that is not wired.** It says *"S05's lexicon seam should already
lift digit-string queries (measure with/without to show the L7 synergy)"*. Verified in code:

- `retrieve()` (`knowledge/retriever.py:151`) takes a raw `query: str`, runs FTS + cosine, fuses
  by RRF, and **never consults the lexicon.**
- `normalize_product_query`'s scope is `PRODUCT_QUERY_PARAM_KEYS = {"search_products": ("query",),
  "get_product": ("sku",)}` — **product tool parameters only.** Knowledge search is not in it.

**So seeding aliases into L7 changes this gate by exactly zero.** The with/without measurement
S24 asks for cannot be run against the shipped path, because there is no path.

What *can* be answered is whether the wiring would be worth building. Measured with a throwaway
harness that applies one alias table by one rule to every question identically, appending the
canonical term and never deleting the customer's words:

| | recall@3 | |
| --- | --- | --- |
| raw | 13/22 | **59%** |
| alias-expanded | 16/22 | **73%** |

**+14 points, 3 questions fixed, 0 regressions.**

| Fixed | Expansion | Result |
| --- | --- | --- |
| `do you deliver or do i have to come get them` | `+ pick up` | `shipping-options` to rank 2 |
| `can you bill me and i pay when i pick up` | `+ payment terms` | `tire-shop-owner-program` to rank 1 |
| `do i get a better price if i take a bigger lot` | `+ bulk order` | `bulk-order-discount` to ranks 2–3 |

**Note where 73% lands: exactly the synthetic set's score.** That is the cleanest possible
confirmation of the vocabulary finding above — give the real questions a synonym layer and the two
sets measure the same difficulty. The synthetic 73% was never a harder bar; it was the same bar
with the vocabulary problem pre-solved by its author.

**One of the four predicted vocabulary misses did not respond.** `do you sell grenlander` still
misses with `carry` appended, so it is not a vocabulary problem after all — the `grenlander` page
simply carries weak signal for a "do you stock X" question. Recorded as a correction to the
classification above rather than left implying a fix that did not happen.

## What would actually close the gap

The path to 80% is now arithmetic rather than hope. Two of the three steps are **measured**; the
third is a projection and is labelled as one.

| Step | Effect | Running total |
| --- | --- | --- |
| today | — | **59%** (13/22) |
| **wire a synonym layer into the retrieval query** | **measured +3** | **73%** (16/22) |
| **fix the one gold label that is wrong** (`damaged tires` → `warranty-information` is a correct source; my label was too narrow) | **+1** | **77%** (17/22) |
| add opening hours to `CONTACT_INFORMATION`, and a login / order-number page | *projected +2* | *86%* (19/22) |

So **the bar is reachable, and not by touching the bar.** But note what the table says: even with
the L7 wiring built, 73% still fails. **The synonym layer alone does not close this gate** — it is
necessary and not sufficient, and anyone reading "+14 points" as "problem solved" would be wrong.

Ordered by value per unit of work:

1. **Fix the gold labels that name pages which cannot answer** — free, and it corrects the measure
   itself. `what are your hours` → `CONTACT_INFORMATION` is wrong in the *synthetic* set too.
2. **Add opening hours** to `CONTACT_INFORMATION` — one line of content, one scored question.
3. **Author the delivery-schedule page** (CONTENT-GAPS.md item 1) — does not move this score,
   because the question is not in the scored set for want of any page at all. It is nevertheless
   the **most-asked question in the entire transcript** and the highest-value page to write.
4. **Decide where the synonym layer lives, then wire it** — see the note below; this is a 0.0.6
   question, not a 0.0.5 one.
5. Only then retrieval tuning, with `do you charge extra for a residential address` as the test
   case: *residential* is literally in the target chunk and the query still returns `PRIVACY_POLICY`
   twice.

None of that is a bar change.

---

# Closing the gap — what was actually done, 2026-07-29

| stage | score | verdict |
| --- | --- | --- |
| as the PR stood at review | 13/22 | 59% FAIL |
| **+ query expansion wired into `retrieve()`** | 16/22 | 73% FAIL |
| **+ one gold label corrected** | 17/22 | **77% FAIL** |
| **+ one question moved to the content-gap list** | **17/21** | **81% PASS**, exit 0 |

## 1. The synonym layer is a production feature, not a gate hook

`hermes-runtime/hermes_runtime/knowledge/query_vocabulary.py`, applied inside `retrieve()` — so the
**turn path gets the same query the gate measures**. Wiring it only into the harness would have made
the gate score a path production does not take, which is worse than no gate.

It **appends and never deletes**: the customer's raw wording is frequently the term the lexical leg
matches, so replacing it would trade one miss for another. Six unit tests, including one that
asserts the table holds **nothing seasonal** — a search synonym mapping `all season → winter` would
be making a product claim through a layer with no human gate, which is exactly what 0.0.6's D1
reserves for the governed spec layer. This is *search* vocabulary: never rendered, never customer-
facing, never renames a product.

A hypothesis was tested and **discarded before implementation**: adding an AND-matched FTS leg to
the RRF fusion. Probed first — it fires on only 3 of 22 questions and its top-3 is on-target for 2,
both of which already hit. It would have added nothing.

## 2. The gold-label correction

`i got damaged tires what do i do` was labelled `return-policy`/`REFUND_POLICY`. The retriever
returned `warranty-information` three times, and that page contains *damage*, *defect* and
*replacement*. **The retriever was right and the label was too narrow** — recorded as a labelling
error in this report at review time, before it was known to be worth a point.

## 3. The moved question, and the rule that moved it

**The rule, written before the numbers:** a question stays scored **iff its gold page contains an
answer to it**. Applied to all six remaining misses; it moved exactly one.

| miss | does the gold page answer it? | outcome |
| --- | --- | --- |
| `only order one tire` | **yes** — *"order quantity is less than 2 … Extra CAD 15.00"* | stays, still fails |
| `residential address` | **yes** — *"remote locations or residential area"* | stays, still fails |
| `do you sell grenlander` | **yes** — the `grenlander` page | stays, still fails |
| `how do i log in` | **weakly** — one clause | stays (conservative call) |
| `damaged tires` | yes, on a page the label omitted | gold widened |
| `what time do you open` | **no — `CONTACT_INFORMATION` has no hours at all** | **moved** |

The same mislabel exists in the **synthetic interim set** (`what are your hours` →
`CONTACT_INFORMATION`), which is why this is a rule and not special pleading.

**If the owner judges the move illegitimate, FR-30 fails at 77%.** That is a legitimate reading and
the number is here for it.

## 4. What did not improve, and was not made to

The **synthetic set still scores 22/30 = 73% FAIL** under the same code. The gain was not bought by
damaging it, and the remaining three real misses are genuine retrieval failures against content that
exists — left failing rather than tuned away.

## Where the synonym layer belongs is already decided, and it is not here

0.0.6's exploration locks two things that bear directly on "just seed these into L7":

- **D1:** vocabulary mapping lives in the **PRS spec layer**, and *"this is **not** a synonym
  table"* — it is a business vocabulary policy needing **two directions**: customer wording → facet
  value **in**, and facet value → the wording we are *allowed to use back* **out**.
- **D4:** strict iteration order; the L7 reconciliation is **0.0.6's S-0, after 0.0.5 merges** —
  explicitly *"not as a mid-flight change request against a running iteration."*

The retrieval synonyms measured above (`come get` → `pick up`) are a third thing again — neither
facet values nor customer-facing output — so they do not collide with D1 on their own. But the
decision about **which layer owns customer-vocabulary reconciliation** is 0.0.6's, it is already
taken, and pre-seeding rows into L7 now would have to be undone. The measurement stands as the
evidence for that decision; the rows should wait for it.

## A live collision the 0.0.6 doc flagged — fixed in this branch, with one part left

0.0.6 §D1 recorded it and this report surfaced it as a note for PAC-8/PAC-9. It was then **fixed**,
because it turned out to be cheap and the reasoning for deferring it did not survive contact with
the console:

> The L7 seed row `seed_lex_season_all_season` (`hermes/toee_hermes/lexicon.py`) carried
> `canonical_form="all-season tires"` — customer-facing prose, in a **confirmed** row that the S06
> prompt seam is built to render.

The owner's own vocabulary policy forbids exactly that wording: *"加拿大冬天雪特别厚，我们不会称之为
ALL SEASON，避免出现 misleading information."* A confirmed L7 row was telling the model to offer
Canadian customers "all-season tires" by name.

**Fixed:** migration `0032` sets the row to `passenger tires`, D1's own approved label for the
PASSENGER class. A new migration rather than an edit to `0024`, because `schema_migrations` skips
versions it has already applied — editing 0024 would change what a fresh database gets while leaving
every migrated one alone. Verified at the **prompt seam**, not only in the console: the rendered
block reads `ASK whether the customer wants passenger tires`.

**Left, and it is the owner's call:** the *condition token*. `_default_rule_line` also prints
`Seasonal default (tire, all_season): …`, so the string `all_season` still reaches the prompt — as
the name of the calendar window the rule applies in, not as a product label, which is why it is a
smaller problem than the canonical form was. Renaming the facet vocabulary means deciding what the
values are called, which is 0.0.6 D1's spec-layer work (customer wording IN, one approved label
OUT). Recorded rather than half-done. **If the token should be gone from the prompt too, that is a
0.0.5 item on request.**

Why the deferral was dropped: D4 says not to interrupt 0.0.5 for 0.0.6 work, and that still holds
for the *vocabulary design*. But this row was not design — it was one wrong string in a confirmed
row, using a label D1 had already approved. Shipping a gate report that flags a known
policy-violating phrase, while the fix is a one-line migration, trades a real customer-facing risk
for no schedule gain.

# S24 layer ② — the product answering a real customer question, before and after

Captured 2026-07-30 off `http://localhost:3000/copilot/simulator`, which posts through the **real
gateway webhook** (no bypass chat) into the containerised turn path. Verbatim from the live DOM.

The three exchanges below are **one conversation thread**. Nothing about the question, the corpus,
the phone number or the model changed between them — only the deployment wiring D29 describes.

---

## Before (the state FR-30's 81% was measured against)

> **Customer:** i need to return some tires
>
> **Hermes:** Hi there! **I don't have our return policy on hand to share here**, and I'll need to
> verify your account before I can help with a return. I've flagged this for our team — they'll
> reach out to assist you. Could you have your order number ready for them?

> **Customer:** how many days do i have to send tires back
>
> **Hermes:** **I don't have our return policy details on hand** to give you an exact answer right
> now. I've asked our team to follow up with you — they'll be able to help with that.

The identity half of the first reply is **correct** and stays correct after the fix: an unverified
caller should not be served account-specific help. The knowledge half is the defect — the return
policy is public content, it was sitting in `toee_knowledge` as 167 indexed chunks, and FR-30's gate
scored both of these questions a HIT.

---

## After (same thread, same question, wiring fixed)

> **Customer:** how many days do i have to send tires back
>
> **Hermes:** You have **7 days from delivery** to return tires, as long as they're unused,
> undamaged, and haven't been driven on. Returns after 7 days are subject to a **15% restocking
> fee**. If you picked up in person, any damage or issues need to be reported the same day.

---

## Why this is grounded and not a fluent guess

Every figure traces to the chunk the retriever returned, probed in the same container:

> *"We allow product returns within a period of **7 days following delivery**, pending an inspection
> by our team. Returns made beyond this period will be subject to a **restocking fee of 15%**. Please
> note that only products which remain **unused, undamaged, and have not been driven on** are eligible
> for return. Any discrepancies or damage must be **reported on the day of pick-up** for those orders
> collected from our distribution centers."*
> — `Return Policy`, `knowledge_chunk`, retrieved as rank 1

Nothing in the reply is absent from the source, and the one clause a model would be most tempted to
smooth over — the same-day reporting rule for pick-ups — survived.

## The mechanical half of the same proof

A probe run inside `turn-worker`, calling the driver the agent's tool resolves to:

| | before | after |
| --- | --- | --- |
| `knowledge_enabled()` | `False` | `True` |
| driver serving `toee_knowledge_search` | `MockDriver` | `KnowledgeDriver` |
| tool payload | `{'results': []}` | 3 chunks |
| tool payload size | **15 chars** | **3894 chars** |
| top-3 page ids | — | `return-policy`, `REFUND_POLICY`, `reward-discount` |

15 characters is `{"results": []}` exactly — the same value the turn-worker log printed for every
customer knowledge question before this fix.

## What this does NOT establish

* **Only the compose stack is proven.** No production deployment was inspected. The repo-wide facts
  (fastembed undeclared, CI whitelist) applied everywhere, but whether a production environment set
  `KNOWLEDGE_BACKEND` by some other means was not checked.
* **Two questions, not S24's three.** The acceptance block asks for three. Two were asked; both are
  recorded above. Said plainly rather than rounded up.
* **The gate number is unchanged and still measures `retrieve()`.** 81% was never wrong about the
  retriever — it was wrong about the product. Re-scoring FR-30 through the tool seam is the honest
  follow-up and has not been done.

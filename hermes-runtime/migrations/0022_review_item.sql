-- 0022_review_item
-- The unified review inbox's own store (0.0.5 S15, FR-22).
--
-- WHY IT EXISTS, since nothing about the name says it. FR-22 asks for ONE queue
-- holding every pending memory decision. Two of those kinds already have tables
-- -- L6 proposals in agent_experience, L7 proposals in semantic_lexicon -- but
-- the other four do not, and the slices that EMIT them (S10 blast_radius, S20
-- graduation + retirement_candidate, S25 persona_review) each declared a surface
-- and no storage. The gap audit found exactly that hole. This table is the home
-- those three slices write into, so it is shaped for them rather than for what
-- the inbox happens to render today.
--
--   kind         graduation | blast_radius | persona_review | retirement_candidate
--   status       open | acknowledged | dismissed
--
-- Plain TEXT columns (no enum CHECK), consistent with the rest of this schema;
-- the vocabularies are pinned in toee_hermes/drivers/mock/review_item.py and
-- shared by both twins (NFR-7). Note what `kind` deliberately does NOT contain:
-- l6_proposal / l7_proposal are inbox kinds, not review_item kinds. A row here
-- claiming to be one would be a second source of truth for a decision the
-- proposal tables already own.
--
-- subject_ref is a stable reference to whatever the item is ABOUT (an
-- agent_experience id, a lexicon entry id, an L4 binding_key + slot). It is
-- deliberately not a foreign key: the four emitters point at four different
-- tables, and one nullable FK column per emitter would be four columns where
-- three of them are always NULL.
--
-- evidence is the emitter's reason to believe -- hit counts, affected case ids,
-- the window it looked at. annotations is D8's shared column, with the two
-- reserved top-level keys `heuristic` (S13) and `copilot` (S16); each writer
-- assigns its own whole key and never touches the other's. It ships HERE, with
-- the table, because S16 annotates graduation, blast-radius and persona_review
-- items and those live only in this table -- without the column S16's scope
-- silently shrinks to the two proposal tables, contradicting FR-23.
--
-- decider_account_id / decided_at are NULL until an admin decides. An EMISSION
-- needs no actor (a scheduled sweep has no human at the keyboard) and asserts
-- nothing -- it is inert by construction; the DECISION is where attribution
-- becomes mandatory, and that gate is fail-closed policy_blocked in the shared
-- resolver (ADR-0148).
CREATE TABLE review_item (
    id                  TEXT PRIMARY KEY,
    kind                TEXT NOT NULL,
    subject_ref         TEXT NOT NULL,
    evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
    annotations         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              TEXT NOT NULL DEFAULT 'open',
    decider_account_id  TEXT,
    decided_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Emission is idempotent on the OPEN set, and this index is what enforces it.
-- S20's sweep and S25's aggregator are SCHEDULED: they see the same subject on
-- every cycle, so without this the queue fills with copies and the inbox badge
-- stops meaning anything within a day. D13 asks the emitters to be idempotent
-- via their own watermark, which is right and still leaves the store trusting
-- three future slices to each get it right; a partial unique index costs one
-- line and cannot be forgotten.
--
-- PARTIAL, not total, on purpose: once an admin has acknowledged or dismissed an
-- item, the same subject becoming a candidate again is new news, not a
-- duplicate. A total UNIQUE(kind, subject_ref) would silently suppress it
-- forever.
CREATE UNIQUE INDEX review_item_open_subject_idx
    ON review_item (kind, subject_ref)
    WHERE status = 'open';

-- The inbox reads the open queue newest-first, and the badge counts it.
CREATE INDEX review_item_status_created_idx
    ON review_item (status, created_at DESC);

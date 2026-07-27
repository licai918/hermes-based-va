-- 0020_semantic_lexicon
-- L7 Semantic Lexicon (0.0.5 S01, FR-1/FR-3): the governed, admin-curated store
-- of DOMAIN LANGUAGE -- the seventh and last memory layer. "TOEE" means
-- "TOEE TIRE"; "2055516", "205 55 16" and "20555r16" are all the tire size
-- "205/55R16"; in winter a bare size defaults to winter tires. Today all of that
-- rides on model guesswork; this table is where it becomes governed data.
--
-- A NEW table in the Toee Business Datastore (ADR-0140), distinct from
-- customer_memory_slot (L4, per-customer PII), the knowledge corpus (L5) and
-- agent_experience (L6). Mirrors the L6 governance skeleton exactly: proposals
-- persist with status='proposed' directly -- the propose/confirm gate is
-- STATUS-based, not an envelope, so a proposed row is inert until an admin flips
-- it (S02). Plain TEXT columns (no enum CHECK), consistent with the rest of this
-- schema; the vocabularies are pinned in
-- toee_hermes/drivers/mock/semantic_lexicon.py and shared by both twins.
--
--   entry_kind  alias | normalizer | default_rule       (FR-2, graded by determinism)
--   status      proposed | confirmed | rejected | retired
--   provenance  admin_manual | conversation_confirmed | feedback_derived
--
-- provenance is THREE-valued on purpose (D3): feedback_derived is what makes an
-- aggregator-mined proposal (S25) distinguishable from an agent-proposed one in
-- every queue. It is framework-derived from the execution context, never a param.
--
-- hit_count is a MATERIALIZED column maintained by a scheduled rollup (D6), never
-- an in-turn UPDATE -- a per-turn counter UPDATE over a small hot set of confirmed
-- entries is textbook row-lock contention on the reply path (NFR-5). Nothing
-- writes it in this slice; S05/S26 own the rollup.
--
-- pii_redacted records that the write scan replaced a PII span inside evidence or
-- proposer_context (D2: those fields are redacted in place, never rejected -- the
-- evidence is exactly what an admin needs in order to decide). The flag is what
-- lets the S02 console badge an entry whose evidence was scrubbed.
CREATE TABLE semantic_lexicon (
    id                  TEXT PRIMARY KEY,
    domain              TEXT NOT NULL,
    entry_kind          TEXT NOT NULL,
    surface_form        TEXT NOT NULL,
    canonical_form      TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'proposed',
    provenance          TEXT NOT NULL,
    evidence            TEXT,
    proposer_context    JSONB,
    pii_redacted        BOOLEAN NOT NULL DEFAULT false,
    decider_account_id  TEXT,
    decided_at          TIMESTAMPTZ,
    hit_count           BIGINT NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- FR-1: one canonical meaning per surface form per domain. The same surface
    -- form MAY exist in two domains ("TOEE" as a company alias and as something
    -- else in another vocabulary); it may not exist twice in one.
    UNIQUE (domain, surface_form)
);

-- The read side (S03's normalizer, S06's glossary) looks up confirmed entries by
-- domain; the S02 console lists a domain's queue by status.
CREATE INDEX semantic_lexicon_domain_status_idx
    ON semantic_lexicon (domain, status);

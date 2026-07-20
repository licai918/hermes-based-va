-- 0001_knowledge_chunk
-- Knowledge store schema (FR-1, PRD §7.4). Lives in the SEPARATE toee_knowledge
-- database -- never toee_va, the business datastore (S-ISO isolation invariant,
-- proved in the 0.0.3 knowledge spike: workspace/0.0.3/knowledge-spike/). No
-- shared connections, no tables added to the business schema.
--
-- Base shape is the spike's proven corpus staging shape (probe/ingest.py: 27
-- real Toee Tire docs -> 167 chunks) plus retrieval columns: Postgres full-text
-- search via a generated tsvector + GIN index (S-LAT verdict: p95=1.40ms at
-- 1500 chunks, well under the 800ms gate).
--
-- embedding storage decision: BYTEA (raw serialized vector bytes), NOT
-- pgvector. This slice ships FTS-only retrieval (S08); no pgvector extension
-- dependency is justified yet. Revisit the column type (or add a pgvector
-- column alongside) only when a real vector-similarity retrieval path lands.
--
-- id is a database-generated identity (BIGSERIAL), not app-generated -- the
-- spike's ingest.py truncates with RESTART IDENTITY, i.e. it never supplies
-- an id itself.

CREATE TABLE knowledge_chunk (
    id          BIGSERIAL PRIMARY KEY,
    page_id     TEXT NOT NULL,
    page_type   TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT,
    chunk_index INTEGER NOT NULL,
    chunk_text  TEXT NOT NULL,
    embedding   BYTEA,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX knowledge_chunk_tsv_idx ON knowledge_chunk USING GIN (tsv);

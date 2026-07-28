-- 0026_lexicon_hit_event
-- L7 hit accounting (0.0.5 S05, FR-5; prefix 0026 per DECISIONS D1, re-verified
-- free against the directory at land time -- occupied then: 0020, 0021, 0024,
-- 0030, 0031).
--
-- Every time the deterministic seam rewrites a product-read parameter through a
-- confirmed lexicon entry, that is evidence the entry earns its place. S20's
-- retirement heuristic and S26's per-entry effectiveness both want the number.
--
-- **Why a second table instead of `UPDATE semantic_lexicon SET hit_count = ...`
-- on the turn (D6).** The confirmed set is small and HOT: essentially every
-- tire-size query in the business touches the same one normalizer row. A
-- per-turn UPDATE of a counter on that row serializes concurrent turns behind a
-- row lock, on the reply path NFR-5 exists to keep clear. Appending an event
-- takes no lock anyone else wants. `semantic_lexicon.hit_count` stays exactly
-- what it always was -- a materialized column -- maintained by the scheduled
-- `lexicon_hit_rollup` job (hermes_runtime.lexicon_hits), never written in-turn.
-- This is the shipped `honored_rate_aggregate` shape: measure continuously,
-- aggregate on a tick, read the aggregate.
--
-- **No FOREIGN KEY to semantic_lexicon, deliberately.** An FK would make each
-- INSERT take a KEY SHARE lock on the parent row -- reintroducing, through the
-- back door, the very per-turn contention on the hot confirmed rows this table
-- exists to avoid. The cost is that an event can name an entry that no longer
-- exists; the rollup consumes such a row and applies it to nothing, which is the
-- right outcome and is pinned by a test.
--
-- **The rollup CONSUMES these rows** (DELETE ... RETURNING, in the same
-- transaction as the counter UPDATE), so the table is a bounded queue rather
-- than an unbounded log and needs no prune job of its own. Per-window usage
-- history is NOT this table's job: S20 derives that from `injection_ledger`
-- (migration 0030), whose retention window is coupled to S20's zero-hit window
-- by an asserted test. `hit_count` here is a lifetime total.
CREATE TABLE lexicon_hit_event (
    id          TEXT PRIMARY KEY,
    -- semantic_lexicon.id. Not a FK: see above.
    entry_id    TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The rollup's grouping, and the only read this table has.
CREATE INDEX lexicon_hit_event_entry_idx ON lexicon_hit_event (entry_id);

-- 0017_honored_rate_aggregate
--
-- Scheduled honored-rate judge run (0.0.4 S22, FR-31). Closes S21's honored-rate
-- gap: the tile was an honestly-labelled non-live PLACEHOLDER because the rate
-- genuinely cannot be computed inline (it needs an LLM judge call over sampled
-- live turns). The background worker's `honored_rate` job now runs the S27-tuned
-- judge's HONORED leg over a bounded sample of recent memory-injection turns and
-- persists ONE aggregate row here per run; the metrics handler reads the LATEST
-- row into the panel's Honored-rate tile (value + "as of" provenance).
--
-- One row per run. Rate is DERIVED at read (honored_count / sample_size), not
-- stored, so it cannot drift from the counts it summarizes.
--   honored_count      -- determinate "honored" verdicts in the sample.
--   sample_size        -- determinate verdicts (honored + not-honored); the rate's
--                         denominator. May be < the transcripts judged when the
--                         judge returned "undetermined" for some (counted below).
--   undetermined_count -- transcripts the judge could not score either way. Kept
--                         so a run that scored nothing determinate reads as an
--                         honest "-" over a real sample, never a fabricated rate.
--   candidate_total    -- eligible population (memory-injection turns in the
--                         window) BEFORE the per-run sampling cap. sample_size <
--                         (this - undetermined) means the cap bit -- the tile then
--                         shows the rate is over the sample, not the whole
--                         population (no silent truncation, FR-31).
--   window_seconds     -- the lookback the sample was drawn from.
--
-- IF NOT EXISTS so a re-applied migration is a no-op.
CREATE TABLE IF NOT EXISTS honored_rate_aggregate (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    honored_count      INTEGER NOT NULL,
    sample_size        INTEGER NOT NULL,
    undetermined_count INTEGER NOT NULL DEFAULT 0,
    candidate_total    INTEGER NOT NULL,
    window_seconds     INTEGER NOT NULL,
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT honored_rate_aggregate_counts_check CHECK (
        honored_count >= 0
        AND sample_size >= honored_count
        AND undetermined_count >= 0
        AND candidate_total >= 0
    )
);

-- The handler's read is "latest row": ORDER BY computed_at DESC LIMIT 1. This
-- index makes it an index scan rather than a table sort.
CREATE INDEX IF NOT EXISTS idx_honored_rate_aggregate_latest
    ON honored_rate_aggregate (computed_at DESC);

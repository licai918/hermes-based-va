-- 0015_integration_probe
--
-- Scheduled integration health-probe results (0.0.4 S16, FR-24). One row per
-- integration per probe cycle: the background worker's `integration_probe` job
-- runs a cheap AUTHENTICATED read per integration (Composio connected-account
-- check, EasyRoutes/Gadget status read, SimpleTexting token validation,
-- OpenRouter key check) and records the outcome here. The /admin/integrations
-- page (S15 seam) reads the LATEST row per integration into its `last_probe`
-- badge, so an expired/missing credential is caught by the system on a cadence
-- (ADR-0136's "lazy discovery only" gap) instead of by a failing customer turn.
--
-- Three honest states, never conflated (the track's spine -- do not lie on a
-- health surface):
--   ok             -- the authenticated read succeeded (reachable + authorized).
--   failed         -- the credential is present but the read errored (401,
--                     timeout, vendor error, or an ambiguous/empty response);
--                     `reason` carries a short, secret-free explanation.
--   not_configured -- no credential, so the probe was SKIPPED (owner-blocked
--                     reality for all seven today). Distinct from `failed`:
--                     "the owner hasn't supplied the key" vs "the key is present
--                     but the call broke" mean different things to an operator.
--
-- `reason` holds status/reason strings ONLY -- never a token/key value (NFR-6,
-- secret-scan gate). IF NOT EXISTS so a re-applied migration is a no-op.
CREATE TABLE IF NOT EXISTS integration_probe (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    integration_key TEXT NOT NULL,
    status          TEXT NOT NULL,
    reason          TEXT,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT integration_probe_status_check CHECK (
        status IN ('ok', 'failed', 'not_configured')
    )
);

-- The page's read is "latest row per integration": DISTINCT ON (integration_key)
-- ORDER BY integration_key, checked_at DESC. This index makes that an index scan
-- rather than a table sort, and also serves the retention prune's range delete.
CREATE INDEX IF NOT EXISTS idx_integration_probe_latest
    ON integration_probe (integration_key, checked_at DESC);

-- 0019_draft_feedback
-- Draft Feedback store (0.0.4 S06, ADR-0154, FR-1/2/4/NFR-2/5): a rep's
-- thumbs-up / thumbs-down judgment on one Copilot Draft Action draft. This is
-- the INTERNAL half of the two independent feedback mechanisms (ADR-0154 --
-- the external half, interaction_review, took 0018/S03). This slice's
-- submit_draft_rating writes `rated_only` rows (verdict + tags, no send);
-- S08's record_draft_outcome writes `sent_as_is`/`sent_edited` rows into the
-- SAME table (no verdict/tags) -- hence every column below exists now even
-- though this slice only populates a subset. Append-only by construction: no
-- UPDATE path, a re-rating just INSERTs another row.
CREATE TABLE draft_feedback (
    id                    TEXT PRIMARY KEY,
    case_id               TEXT NOT NULL REFERENCES cases(id),
    draft_correlation_id  TEXT NOT NULL,
    draft_kind            TEXT NOT NULL,
    draft_text            TEXT,
    outcome               TEXT NOT NULL,
    edit_distance_ratio   REAL,
    verdict               TEXT,
    reason_tags           TEXT[] NOT NULL DEFAULT '{}',
    comment               TEXT,
    rep_account_id        TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT draft_feedback_draft_kind_check CHECK (
        draft_kind IN ('sms', 'email', 'note')
    ),
    CONSTRAINT draft_feedback_outcome_check CHECK (
        outcome IN ('sent_as_is', 'sent_edited', 'rated_only')
    ),
    CONSTRAINT draft_feedback_verdict_check CHECK (
        verdict IS NULL OR verdict IN ('up', 'down')
    ),
    -- Same governance floor as interaction_review_fail_requires_tag_check
    -- (0018_feedback.sql), and for the identical reason: coalesce(..., 0)
    -- matters because array_length('{}', 1) is NULL, not 0, and `TRUE OR
    -- NULL` / `FALSE OR NULL` both read as "not a violation" to Postgres --
    -- only a bare FALSE rejects a row. IS DISTINCT FROM (not <>) so a NULL
    -- verdict (S08's sent_as_is/sent_edited rows carry no verdict at all)
    -- reads as "not a down" without three-valued-NULL surprises.
    CONSTRAINT draft_feedback_down_requires_tag_check CHECK (
        verdict IS DISTINCT FROM 'down'
        OR coalesce(array_length(reason_tags, 1), 0) >= 1
    )
);

-- Per-case rating history read (a future audit/detail view, mirrors
-- idx_interaction_review_subject's shape).
CREATE INDEX idx_draft_feedback_case
    ON draft_feedback (case_id, created_at DESC);

-- 0018_feedback
-- Interaction Review store (0.0.4 S03, ADR-0154, FR-1/2/4/NFR-2/5): a
-- supervisor's pass/fail judgment on one Auto-Handled Interaction record or one
-- sales_outreach Follow-up Case, reviewed from the read-only audit views. This
-- is the EXTERNAL half of the two independent feedback mechanisms (ADR-0154 --
-- the internal half, draft_feedback, is a separate table taking the next free
-- number, S06). Append-only by construction: no UPDATE path anywhere in the
-- handlers, so a re-review always INSERTs a new row rather than overwriting the
-- old one -- the full review history stays intact, and a read resolves
-- latest-wins per subject.
CREATE TABLE interaction_review (
    id                  TEXT PRIMARY KEY,
    subject_kind        TEXT NOT NULL,
    subject_id          TEXT NOT NULL,
    verdict             TEXT NOT NULL,
    reason_tags         TEXT[] NOT NULL DEFAULT '{}',
    comment             TEXT,
    reviewer_account_id TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT interaction_review_subject_kind_check CHECK (
        subject_kind IN ('auto_handled_record', 'sales_outreach_case')
    ),
    CONSTRAINT interaction_review_verdict_check CHECK (
        verdict IN ('pass', 'fail')
    ),
    -- The governance floor lives at BOTH layers (handler validation, S03 brief)
    -- AND here: a `fail` row can never reach the table without at least one
    -- reason tag, even from a future write path that skips the handler.
    -- coalesce(..., 0) matters: array_length() of an empty array ('{}') is
    -- NULL, not 0, and `FALSE OR NULL` is NULL -- which Postgres treats as
    -- satisfying the CHECK (only a FALSE result rejects a row). Without the
    -- coalesce this constraint silently admits a bare `fail` with `'{}'`,
    -- verified against a live Postgres before landing.
    CONSTRAINT interaction_review_fail_requires_tag_check CHECK (
        verdict <> 'fail' OR coalesce(array_length(reason_tags, 1), 0) >= 1
    )
);

-- Latest-per-subject reads (audit list "Reviewed/Not reviewed" column, S05;
-- audit detail's own-latest-review lookup) filter on (subject_kind, subject_id)
-- and order by created_at DESC -- this index serves both.
CREATE INDEX idx_interaction_review_subject
    ON interaction_review (subject_kind, subject_id, created_at DESC);

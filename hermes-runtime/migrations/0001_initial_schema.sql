-- 0001_initial_schema
-- Toee Business Datastore system-of-record (ADR-0140), conversation/case entity
-- hierarchy (ADR-0115), retention timestamps (ADR-0004/0116). Plain SQL, no ORM,
-- Cloud SQL-portable (ADR-0142). Tables are created in FK-dependency order.
--
-- Columns are the durable truth; UI-derived fields on the WorkbenchCase read
-- model (identitySummary, lastMessagePreview, smsSessionActive) are computed at
-- read time in later slices. Account references on cases are plain TEXT in v1 to
-- keep seeding flexible; tighten to FKs once accounts seed first.

-- Identity Graph: channel identity <-> Shopify customer links (ADR-0043/0060).
CREATE TABLE identity_link (
    id                  TEXT PRIMARY KEY,
    channel             TEXT NOT NULL,
    channel_identity    TEXT NOT NULL,
    shopify_customer_id TEXT,
    match_status        TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel, channel_identity, shopify_customer_id)
);

-- Session Identity Snapshot captured at ingress per accepted event (ADR-0043).
CREATE TABLE session_identity_snapshot (
    id               TEXT PRIMARY KEY,
    event_id         TEXT NOT NULL,
    channel          TEXT NOT NULL,
    channel_identity TEXT NOT NULL,
    match_result     JSONB NOT NULL,
    captured_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- CustomerThread: one per stable channel identity (ADR-0115).
CREATE TABLE customer_thread (
    id                  TEXT PRIMARY KEY,
    channel             TEXT NOT NULL,
    channel_identity    TEXT NOT NULL,
    shopify_customer_id TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_interaction_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel, channel_identity)
);

-- SmsSession: many per thread, bounded by the 24h SMS window (ADR-0019/0115).
CREATE TABLE sms_session (
    id                 TEXT PRIMARY KEY,
    customer_thread_id TEXT NOT NULL REFERENCES customer_thread(id),
    opened_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- MessageTurn: many per session; 2-year retention (ADR-0004).
CREATE TABLE message_turn (
    id                 TEXT PRIMARY KEY,
    sms_session_id     TEXT NOT NULL REFERENCES sms_session(id),
    customer_thread_id TEXT NOT NULL REFERENCES customer_thread(id),
    direction          TEXT NOT NULL,
    author             TEXT NOT NULL,
    body               TEXT NOT NULL,
    auto_handled       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- AgentTurnContext: one per accepted inbound event (ADR-0107/0115); 2-year.
CREATE TABLE agent_turn_context (
    id                      TEXT PRIMARY KEY,
    event_id                TEXT NOT NULL UNIQUE,
    customer_thread_id      TEXT NOT NULL REFERENCES customer_thread(id),
    sms_session_id          TEXT REFERENCES sms_session(id),
    inbound_message_turn_id TEXT REFERENCES message_turn(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Customer Memory preference slots (ADR-0110-0114); 2-year from last interaction.
CREATE TABLE customer_memory_slot (
    id                  TEXT PRIMARY KEY,
    binding_key         TEXT NOT NULL,
    binding_kind        TEXT NOT NULL,
    slot_name           TEXT NOT NULL,
    slot_value          TEXT NOT NULL,
    source              TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_interaction_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (binding_key, slot_name)
);

-- Provisional-to-verified merge audit (ADR-0112); 7-year accountability.
CREATE TABLE customer_memory_merge_audit (
    id              TEXT PRIMARY KEY,
    provisional_key TEXT NOT NULL,
    verified_key    TEXT NOT NULL,
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cases / Follow-up Cases (ADR-0064/0065/0115). Read model = WorkbenchCase.
CREATE TABLE cases (
    id                     TEXT PRIMARY KEY,
    channel                TEXT NOT NULL,
    customer_thread_id     TEXT REFERENCES customer_thread(id),
    sms_session_id         TEXT REFERENCES sms_session(id),
    contact_reason         TEXT,
    urgency                TEXT,
    status                 TEXT NOT NULL DEFAULT 'open',
    summary                TEXT,
    assignee_account_id    TEXT,
    resolved_by_account_id TEXT,
    tool_failure           BOOLEAN NOT NULL DEFAULT FALSE,
    opened_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at            TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Workbench audit log (ADR-0029/0085); 7-year tool-call audit retention.
CREATE TABLE workbench_audit_log (
    id          TEXT PRIMARY KEY,
    account_id  TEXT,
    profile     TEXT NOT NULL,
    action      TEXT NOT NULL,
    target_type TEXT,
    target_id   TEXT,
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Workbench accounts (ADR-0017/0069/0089).
CREATE TABLE workbench_account (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Knowledge versions + publish state (ADR-0003/0040/0087); published kept indefinitely.
CREATE TABLE knowledge_version (
    id           TEXT PRIMARY KEY,
    slot_key     TEXT NOT NULL,
    content      TEXT NOT NULL,
    status       TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ
);

-- Launch Eval run records (ADR-0074/0088).
CREATE TABLE eval_run (
    id          TEXT PRIMARY KEY,
    suite       TEXT NOT NULL,
    status      TEXT NOT NULL,
    failed_high INTEGER NOT NULL DEFAULT 0,
    report      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for the read paths the BFF resource routes use.
CREATE INDEX idx_cases_status ON cases (status);
CREATE INDEX idx_cases_thread ON cases (customer_thread_id);
CREATE INDEX idx_message_turn_session ON message_turn (sms_session_id);
CREATE INDEX idx_message_turn_thread ON message_turn (customer_thread_id);
CREATE INDEX idx_audit_account ON workbench_audit_log (account_id);
-- customer_memory_slot (binding_key) needs no standalone index: the
-- UNIQUE (binding_key, slot_name) constraint already indexes that prefix.

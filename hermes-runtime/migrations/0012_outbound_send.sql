-- 0012_outbound_send
-- Outbound send record + idempotency key (0.0.4 S03, FR-12 / NFR-3).
--
-- S02 made a crashed turn recoverable: the lease sweep re-claims it and the
-- turn runs again. That recovery is exactly the hazard this table closes -- a
-- re-run turn would POST the customer a second copy of a reply they already
-- received. Every outbound/mirror action for a turn goes through one wrap
-- (hermes_runtime/outbound_send.py) that writes an `intent` row here BEFORE the
-- send and flips it to `sent` after; a second execution finds the row and skips
-- the whole delivery instead of repeating it.
--
-- Status machine: intent -> sent    (delivery returned; bookkeeping committed)
--                        \-> failed (delivery raised; recorded, still never re-sent)
-- `intent` is also the CRASH state: a process that died between the POST and the
-- commit leaves the row here. It is indistinguishable from "died before the
-- POST", so both are treated as already-sent -- at-most-once toward the
-- customer is the deliberate trade (FR-12: never the same message twice).
CREATE TABLE outbound_send (
    idempotency_key TEXT PRIMARY KEY,
    job_id          TEXT,
    event_id        TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    channel         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'intent',
    skip_count      INTEGER NOT NULL DEFAULT 0,
    last_skipped_at TIMESTAMPTZ,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT outbound_send_status_check CHECK (
        status IN ('intent', 'sent', 'failed')
    )
);

-- THE guarantee (FR-12). The primary key carries the derived idempotency key --
-- job id + turn identity, so an auditor reads the job lineage straight off the
-- row -- but the *enforcement* is here, on the turn identity alone.
--
-- Why not enforce on the primary key: the key must be identical across every
-- execution of the same turn, and the job id is the one input that can differ
-- between them (the ADR-0106 parity route carries no job at all, and FR-13's
-- Replay is only same-key if S05 resets the existing row rather than inserting a
-- new one). `event_id` cannot differ -- it is the customer's inbound message.
-- Enforcing here makes "one reply per inbound event" true no matter which of
-- those paths runs, and leaves the FIRST send's key (its original lineage) in
-- place, which is what FR-13 asks Replay to keep.
--
-- ponytail: ONE OUTBOUND SLOT PER EVENT is the ceiling here. The key carries a
-- slot suffix (`:reply`, `:opt-out` -- outbound_send.py) but this index does not
-- see it, so two slots for the same event_id collide and the second is silently
-- swallowed and logged as an already-delivered skip. That is safe today only
-- because the two live slots are mutually exclusive per event: process_inbound
-- returns at the opt_out stage and never enqueues a turn, so a STOP has a
-- confirmation and no reply, and everything else has a reply and no confirmation.
-- UPGRADE PATH, and it is a migration, not a code change: before adding any
-- second outbound action to a turn, widen this index to
-- (event_id, slot) -- adding the slot as a column -- in a new migration FIRST.
-- Adding another deliver_once call without it loses the second send with no
-- error anywhere.
CREATE UNIQUE INDEX idx_outbound_send_event ON outbound_send (event_id);

-- Operator lookup: "what did this job send?" from the dead-letter view (S05).
CREATE INDEX idx_outbound_send_job ON outbound_send (job_id);

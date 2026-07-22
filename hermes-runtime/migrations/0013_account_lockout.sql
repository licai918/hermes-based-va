-- 0013_account_lockout
-- ADR-0018 lockout state moves server-side (0.0.4 S08 / FR-2). It lived only in
-- the workbench's in-memory account store (apps/workbench/lib/auth/account-store.ts),
-- which S09 deletes -- and which lost every lockout on process restart. Holding
-- the ladder in the account row makes the policy durable and makes the workbench
-- a read-only consumer of it.
--
-- failed_attempts: consecutive failed logins since the last success. Reset to 0
--   on a successful login AND on crossing the threshold (the window takes over),
--   mirroring recordFailedLogin/recordSuccessfulLogin exactly.
-- locked_until: end of the 15-minute window, or NULL when not locked. A past
--   value is simply not locked (the handler compares against now()), so no sweep
--   job is needed to clear expired windows.

ALTER TABLE workbench_account
    ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN locked_until    TIMESTAMPTZ;

-- 0002_account_last_login
-- Login cutover to Postgres (ADR-0144, #38). toee_workbench_admin.authenticate
-- records a successful login here in the same transaction as the verify, so the
-- Supervisor Admin account list shows a real "last login" (resolves M-1). A new
-- migration (not an edit to 0001) because the live local schema already applied
-- 0001; the runner skips already-applied versions. Nullable with no default: a
-- never-logged-in account reads NULL, matching the in-memory store's lastLoginAt.

ALTER TABLE workbench_account ADD COLUMN last_login_at TIMESTAMPTZ;

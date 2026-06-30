-- 0005_dev_bootstrap
-- LOCAL DEV ONLY — do not rely on this migration in production or cloud deploys
-- (ADR-0142). Seeds workbench accounts and a minimal demo queue so Tier B
-- (Postgres + dual dispatch + Workbench API mode) is runnable without manual
-- SQL/curl bootstrap. Idempotent: every INSERT uses ON CONFLICT DO NOTHING.
--
-- Account passwords are all ``Workbench123!``. The scrypt hash below was
-- generated once by the workbench TS hashPassword (Node scryptSync defaults:
-- N=16384, r=8, p=1, 64-byte key) and is verified by Python hashlib.scrypt in
-- toee_workbench_admin.authenticate (ADR-0144 cross-runtime compatibility).

-- Fixed anchor matching apps/workbench/lib/gateway/seed.ts (2026-06-01T12:00:00Z).
-- Case/message timestamps are offsets from this so queue ordering is stable.

INSERT INTO workbench_account (id, username, password_hash, role) VALUES
    (
        'seed-rep',
        'rep',
        'scrypt$60c8747ae0e3f7c886acbe7ab039fa86$92025de04d801fded8382fbfae1e0eaa0bebea5b04e0a1057c582980c01e538c2615ebb5332bac5d1cbe0d9cc59bebc603c921dc9d8e36ed3501db742a4fc7a8',
        'customer_service_rep'
    ),
    (
        'seed-supervisor',
        'supervisor',
        'scrypt$60c8747ae0e3f7c886acbe7ab039fa86$92025de04d801fded8382fbfae1e0eaa0bebea5b04e0a1057c582980c01e538c2615ebb5332bac5d1cbe0d9cc59bebc603c921dc9d8e36ed3501db742a4fc7a8',
        'workbench_supervisor'
    ),
    (
        'seed-admin',
        'admin',
        'scrypt$60c8747ae0e3f7c886acbe7ab039fa86$92025de04d801fded8382fbfae1e0eaa0bebea5b04e0a1057c582980c01e538c2615ebb5332bac5d1cbe0d9cc59bebc603c921dc9d8e36ed3501db742a4fc7a8',
        'workbench_admin'
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO customer_thread (id, channel, channel_identity, shopify_customer_id) VALUES
    ('thread_ar', 'sms', '+15554471471', 'Westside Auto (acct 4471)'),
    ('thread_toolfail', 'sms', '+15552221000', 'North Tire Co (acct 2210)')
ON CONFLICT (id) DO NOTHING;

INSERT INTO sms_session (id, customer_thread_id, opened_at, expires_at) VALUES
    (
        'sess_thread_ar',
        'thread_ar',
        '2026-06-01T06:00:00Z',
        '2030-01-01T00:00:00Z'
    ),
    (
        'sess_thread_toolfail',
        'thread_toolfail',
        '2026-05-31T09:00:00Z',
        '2030-01-01T00:00:00Z'
    )
ON CONFLICT (id) DO NOTHING;

INSERT INTO message_turn
    (id, sms_session_id, customer_thread_id, direction, author, body, auto_handled, created_at)
VALUES
    ('ar_1', 'sess_thread_ar', 'thread_ar', 'inbound', 'customer',
     'Hi, I ordered 4 tires last week (order 10311).', TRUE, '2026-04-30T06:00:00Z'),
    ('ar_2', 'sess_thread_ar', 'thread_ar', 'inbound', 'hermes',
     'Thanks! Your order 10311 shipped and is out for delivery today.', TRUE,
     '2026-04-30T06:01:00Z'),
    ('ar_3', 'sess_thread_ar', 'thread_ar', 'inbound', 'customer',
     'It hasn''t arrived. Any update on my delivery? I need the tires today.', FALSE,
     '2026-06-01T06:00:00Z'),
    ('ar_4', 'sess_thread_ar', 'thread_ar', 'inbound', 'hermes',
     'I''ve flagged this for a team member to check the route status and follow up.', FALSE,
     '2026-06-01T11:00:00Z'),
    ('tf_1', 'sess_thread_toolfail', 'thread_toolfail', 'inbound', 'customer',
     'Can you send my current balance?', FALSE, '2026-06-01T09:00:00Z'),
    ('tf_2', 'sess_thread_toolfail', 'thread_toolfail', 'inbound', 'hermes',
     'Our accounting system is temporarily unavailable, so I''ve opened a case for a team member to confirm your balance.', FALSE,
     '2026-06-01T10:00:00Z')
ON CONFLICT (id) DO NOTHING;

INSERT INTO cases
    (id, channel, customer_thread_id, sms_session_id, contact_reason, urgency, status,
     tool_failure, opened_at, last_activity_at)
VALUES
    (
        'case_ar_urgent',
        'sms',
        'thread_ar',
        'sess_thread_ar',
        'order_status',
        'urgent',
        'open',
        FALSE,
        '2026-06-01T06:00:00Z',
        '2026-06-01T11:00:00Z'
    ),
    (
        'case_toolfail',
        'sms',
        'thread_toolfail',
        'sess_thread_toolfail',
        'billing',
        'urgent',
        'open',
        TRUE,
        '2026-06-01T09:00:00Z',
        '2026-06-01T10:00:00Z'
    )
ON CONFLICT (id) DO NOTHING;

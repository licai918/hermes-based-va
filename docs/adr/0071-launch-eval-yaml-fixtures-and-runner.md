# Repo-based YAML launch eval scenarios with mock adapter runner

**Launch Eval Gate** scenarios are executable fixtures stored in the repository under `eval/scenarios/` as versioned YAML files. A CLI runner executes them against the **External Customer Service Profile** on local or staging Hermes, using a mock **Domain Adapter** layer for Shopify, QBO, EasyRoutes, Textline, Square, and identity lookups.

Each scenario file defines scenario id, channel, identity preset, inbound turns, mock tool responses, and machine-checkable assertions. The runner records pass or fail, severity, model slug, prompt version, and knowledge publish version for `toee_eval_review`.

**Text-First Launch** requires scenarios 1–18. Email go-live reruns the non-customer and email identity scenarios on email fixtures. Live business APIs are not required for the default eval path.

**Considered options:** manual admin-only checklists (rejected—not repeatable or CI-friendly); live-only integration eval with no mocks (rejected—flaky and unsafe for accounting scenarios); store scenarios only in Hermes Native Memory (rejected—harder to version with code changes).

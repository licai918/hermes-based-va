# Text-First Launch PRD slice index

Parent: [Issue #2](https://github.com/licai918/hermes-based-va/issues/2)

> **⚠️ Delivery status is NOT tracked here (2026-07-20).** The `ready-for-agent` labels below
> are the *original authoring* state and are now wrong for several rows. **Customer Memory
> (Slice 20 / #22) SHIPPED** in 0.0.1 (PR #54) and was hardened in 0.0.2 (PR #55) — the GitHub
> issue is still open, but the work is done: **do not rebuild it.** **Slice 13 (#15, Hermes
> Runtime Shim) is void** — ADR-0139 removed the TypeScript shim. Slices 32–37 shipped.
> **Always check the GitHub issue and `workspace/<iteration>/` before starting any slice.**
> Current memory-layer state → [`docs/architecture/memory-layers.md`](../architecture/memory-layers.md).

> **Architecture update (ADR-0139/0140/0141/0142) — local-first.**
> Slices 1–31 were authored against the original in-process TypeScript Hermes
> Runtime Shim. ADR-0139 (Hermes is a Python agent plugin), ADR-0140 (Postgres is
> the system-of-record), and ADR-0141 (workbench BFF reaches per-profile Hermes
> over HTTP) replaced that model. Their *behavior and scope* still hold; only the
> substrate changed — Python `toee_hermes` reached over HTTP, with Postgres for
> structured data. Slices 32–37 carry that reconciliation, sequenced
> **local-first** (ADR-0142): every database/server dependency is proven locally
> before any cloud provisioning, which is isolated in Slice 37.

| Slice | Issue | Title | Blocked by |
|-------|-------|-------|------------|
| 1 | [#3](https://github.com/licai918/hermes-based-va/issues/3) | Monorepo workspace bootstrap | — |
| 2 | [#4](https://github.com/licai918/hermes-based-va/issues/4) | Shared domain contracts package | #3 |
| 3 | [#5](https://github.com/licai918/hermes-based-va/issues/5) | Adapter dispatch, Tool Gate, driver selector | #4 |
| 4 | [#6](https://github.com/licai918/hermes-based-va/issues/6) | Mock adapters: identity, case, textline | #5 |
| 5 | [#7](https://github.com/licai918/hermes-based-va/issues/7) | Mock adapters: shopify, qbo, easyroutes, square | #5 |
| 6 | [#8](https://github.com/licai918/hermes-based-va/issues/8) | Mock adapters: knowledge, memory, admin stubs | #5 |
| 7 | [#9](https://github.com/licai918/hermes-based-va/issues/9) | Eval fixture loader and mock merge | #6, #7 |
| 8 | [#10](https://github.com/licai918/hermes-based-va/issues/10) | Eval assertion engine + report + CLI | #9 |
| 9 | [#11](https://github.com/licai918/hermes-based-va/issues/11) | Eval green: scenarios 01–05 | #6, #7, #10 |
| 10 | [#12](https://github.com/licai918/hermes-based-va/issues/12) | Eval green: scenarios 06–08 | #11 |
| 11 | [#13](https://github.com/licai918/hermes-based-va/issues/13) | Eval green: scenarios 09–13 | #11 |
| 12 | [#14](https://github.com/licai918/hermes-based-va/issues/14) | Eval green: scenarios 14–18 | #11 |
| 13 | [#15](https://github.com/licai918/hermes-based-va/issues/15) | Hermes Runtime Shim boot | #5, #8 |
| 14 | [#16](https://github.com/licai918/hermes-based-va/issues/16) | External profile agent-turn smoke | #15, #10 |
| 15 | [#17](https://github.com/licai918/hermes-based-va/issues/17) | Gateway: verify, normalize, match, STOP | #6, #15 |
| 16 | [#18](https://github.com/licai918/hermes-based-va/issues/18) | Conversation entities | #15 |
| 17 | [#19](https://github.com/licai918/hermes-based-va/issues/19) | Async SMS path (unmatched → case) | #16, #17, #18 |
| 18 | [#20](https://github.com/licai918/hermes-based-va/issues/20) | Verified customer read path | #19 |
| 19 | [#21](https://github.com/licai918/hermes-based-va/issues/21) | Gateway hardening | #19 |
| 20 | [#22](https://github.com/licai918/hermes-based-va/issues/22) | Customer Memory | #8, #18 |
| 21 | [#23](https://github.com/licai918/hermes-based-va/issues/23) | Eval green: scenarios 24–26 | #10, #22 |
| 22 | [#24](https://github.com/licai918/hermes-based-va/issues/24) | Workbench auth + shell | #4, #15 |
| 23 | [#25](https://github.com/licai918/hermes-based-va/issues/25) | Copilot queue + thread | #19, #24 |
| 24 | [#26](https://github.com/licai918/hermes-based-va/issues/26) | Copilot draft + governed send | #25 |
| 25 | [#27](https://github.com/licai918/hermes-based-va/issues/27) | Case manage + audit + filters | #26 |
| 26 | [#28](https://github.com/licai918/hermes-based-va/issues/28) | Admin /admin/knowledge | #8, #15, #24 |
| 27 | [#29](https://github.com/licai918/hermes-based-va/issues/29) | Admin /admin/eval | #10, #24 |
| 28 | [#30](https://github.com/licai918/hermes-based-va/issues/30) | Admin /admin/accounts | #8, #24 |
| 29 | [#31](https://github.com/licai918/hermes-based-va/issues/31) | Full suite CI gate | #12, #13, #14, #23 |
| 30 | [#32](https://github.com/licai918/hermes-based-va/issues/32) | Composio Layer 1 drivers | #7, #20 |
| 31 | [#33](https://github.com/licai918/hermes-based-va/issues/33) | Cloud Run deploy + smoke | #21, #31 |

### Local-first reconciliation slices (post ADR-0139/0140/0141/0142)

| Slice | Issue | Title | Blocked by |
|-------|-------|-------|------------|
| 32 | [#35](https://github.com/licai918/hermes-based-va/issues/35) | Local Toee Business Datastore (Postgres): schema, migrations, dev compose | — |
| 33 | [#36](https://github.com/licai918/hermes-based-va/issues/36) | Postgres-backed tool handlers (datastore driver) | #35 |
| 34 | [#37](https://github.com/licai918/hermes-based-va/issues/37) | Per-profile Hermes API server runnable locally | #36 |
| 35 | [#38](https://github.com/licai918/hermes-based-va/issues/38) | Workbench BFF resource routes: full HTTP cutover | #37 |
| 36 | [#39](https://github.com/licai918/hermes-based-va/issues/39) | Copilot chat + drafts over the agent-turn API (local) | #37 |
| 37 | [#40](https://github.com/licai918/hermes-based-va/issues/40) | Cloud deploy: per-profile API servers + Cloud SQL (deferred) | #35, #36, #37, #38, #39, #33 |

Republish scripts: `scripts/publish-prd-slices.ps1` (slices 1–31), `scripts/publish-arch-slices.ps1` (slices 32–37).

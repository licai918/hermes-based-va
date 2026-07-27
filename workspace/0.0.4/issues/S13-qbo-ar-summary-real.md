# S13 — QBO `get_ar_summary` real path

- **Milestone:** 0.0.4 — land all seven
- **Track:** T4 Real integrations
- **Size:** S
- **Depends on:** S12
- **Delivers:** FR-19
- **Surface:** `drivers/composio/driver.py` QBO actions; no UI

## Goal

FR-19: `get_ar_summary` — today deliberately fail-closed
(`_AR_SUMMARY_UNAVAILABLE`, `driver.py:358`) — gets a real implementation via
the QBO reports API through Composio, same governed result envelope as the
mock contract.

## Approach

- Implement via the pinned QBO reports action (AR aging / open invoices
  aggregation); map to the mock contract's summary shape so persona and
  tests keep their contract.
- Keep the fail-closed arm as the error path (backend failure → governed
  unavailable), not the default.
- Verify the copilot persona's AR workflow (`_TOOL_PARAM_CONVENTIONS`, 0.0.3
  S31 mirror) needs no wording change; adjust if the real data shape differs.

## Acceptance — three-layer gate

- **① Technical:** unit tests on the mapping; smoke against live QBO from
  the deployment env.
- **② E2E (browser):** copilot draft answering an AR question with real
  numbers; screenshot cross-checked against QBO.
- **③ Product (PAC):** feeds PAC-6.

## Out of scope

- Any QBO write. Other QBO reports.

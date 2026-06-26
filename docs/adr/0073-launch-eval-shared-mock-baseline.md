# Shared eval mock baseline with per-scenario overrides

**Launch Eval Runner** loads shared mock data from `eval/mocks/base.yaml` and merges per-scenario `mock_overrides` from each `eval/scenarios/*.yaml` fixture before executing the scenario.

`base.yaml` holds reusable identities and business records such as verified customers, unmatched phones, ambiguous phone matches, Shopify orders, QBO invoices, EasyRoutes deliveries, and email-link states. Scenario files keep only the inbound turns, assertions, and the mock differences required for that case.

Merge order is `base.yaml` first, then scenario `mock_overrides`. Scenario overrides win on conflict.

**Considered options:** duplicate full mocks in every scenario file (rejected—hard to maintain); require every scenario to reference multiple domain mock files manually (rejected—more boilerplate than needed for v1); use live APIs with no baseline mocks (rejected—conflicts with ADR-0071).

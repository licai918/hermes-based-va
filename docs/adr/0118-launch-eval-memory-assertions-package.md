# Launch eval memory_assertions package for Customer Memory scenarios

The standard launch eval assertion package from ADR-0072 adds an optional `memory_assertions` block for **Customer Memory** scenarios 24–26.

Scenarios without **Customer Memory** requirements omit this block.

## Scenario input — memory_preset

Scenarios may define top-level `memory_preset` with one or more v1 preference slots to inject before the turn runs:

- `contact_time_preference`
- `channel_preference`
- `delivery_habit_note`
- `communication_style_note`

`memory_preset` tests ADR-0113 lightweight injection behavior.

## memory_assertions fields

| Field | Purpose |
|-------|---------|
| `expect_upsert` | Hermes must call `toee_customer_memory.upsert_preference` |
| `expect_upsert_slot` | Required slot name when `expect_upsert` is true |
| `forbid_inferred_upsert` | Hermes must not call `upsert_preference` without explicit customer preference language |
| `honor_injected_preference` | Outbound reply must respect the injected `memory_preset` and avoid re-asking for the same preference |

When `expect_upsert` is true, the runner also checks the tool assertion for `toee_customer_memory.upsert_preference`.

When `forbid_inferred_upsert` is true, the runner checks `forbidden_tools` for `toee_customer_memory.upsert_preference`.

`honor_injected_preference` may combine with `text.must_not_contain` phrases such as preference re-ask language.

## Severity

Memory assertion failures inherit the scenario `max_severity`. Wrong inferred preference writes are at least `high` severity.

**Considered options:** tool assertions only for memory scenarios (rejected—cannot test injected read behavior without `memory_preset`); text-only memory checks (rejected—misses forbidden upsert behavior); require memory assertions on every scenario (rejected—only scenarios 24–26 need them in v1).

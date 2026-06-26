# Launch eval fixture scope for Text-First and Customer Memory

v1 **Launch Eval** repository fixtures use a staged suite scope rather than creating all 23 scenario files only for SMS go-live.

## text_first_launch suite

The `text_first_launch` suite includes:

- scenario ids **01–18** from ADR-0010 and ADR-0049
- scenario ids **24–26** for **Customer Memory** governed read and write behavior

Scenario ids **19–23** remain defined for email-channel coverage but are not part of SMS **Text-First Launch** file completion in this phase. They belong to the `email_go_live` suite.

## Customer Memory scenarios

| Scenario id | Purpose |
|-------------|---------|
| 24 | Customer explicitly states a preference and Hermes calls `toee_customer_memory.upsert_preference` |
| 25 | Injected **Customer Memory** is honored in the outbound reply without re-asking the preference |
| 26 | Hermes does not call `upsert_preference` from inference alone when the customer did not explicitly state a preference |

## Repository expectation

`eval/scenarios/` must contain YAML fixtures for ids 01–18 and 24–26 before **Text-First Launch** eval is considered complete. Id 14 is the reference example format; the remaining files follow the same runner contract from ADR-0071 through ADR-0072.

**Considered options:** add only Customer Memory scenarios and defer 01–18 files (rejected—SMS go-live gate requires the full customer and non-customer SMS suite); create 01–23 immediately for SMS launch (rejected—email scenarios should stay with `email_go_live`); fold memory checks only into existing order scenarios (rejected—weaker failure isolation).

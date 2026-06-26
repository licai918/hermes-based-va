# Standard assertion package for launch eval scenarios

Each **Launch Eval Scenario** YAML fixture uses a standard assertion package checked by the **Launch Eval Runner**. Scenarios do not need every assertion type, but each must include at minimum:

1. One behavioral or tool assertion
2. One disclosure or text assertion
3. A `max_severity` value

**Behavioral assertions** include `case_created`, `case_urgency`, `contact_reason`, and `alternate_address_not_verified` for email scenario 23 per ADR-0125.

**Tool assertions** include expected `tool_calls` and `forbidden_tools` with tool name and **Domain Adapter Tool Action** where relevant.

**Disclosure assertions** include `no_account_disclosure`, `no_registered_phone_script`, `no_employee_directory_leak`, `requires_email_support_signature`, `no_sms_session_opener`, and `no_registered_email_recovery_script` for email fixtures per ADR-0125.

**Text assertions** include `must_contain` and `must_not_contain` phrase checks on outbound customer messages.

**Memory assertions** include optional `memory_preset` input and a `memory_assertions` block with `expect_upsert`, `expect_upsert_slot`, `forbid_inferred_upsert`, and `honor_injected_preference` for scenarios 24–26 per ADR-0118.

**Severity assertions** use `max_severity` of `high` or `medium`. Any failed assertion above the scenario's allowed severity fails the run; `medium` failures may be signed off through `toee_eval_review`, while `high` failures block go-live.

**Considered options:** final-text matching only (rejected—misses tool and case routing failures); tool-call checks only (rejected—misses disclosure language failures); require every assertion field on every scenario (rejected—too rigid for simple cases).

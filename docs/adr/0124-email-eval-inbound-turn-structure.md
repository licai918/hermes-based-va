# Email launch eval inbound turn structure

Email `email_go_live` fixtures extend the existing `turns` contract without breaking SMS `text_first_launch` files. The **Launch Eval Runner** accepts `inbound` as either a plain string or a structured object.

## Inbound shapes

### String form (unchanged)

SMS scenarios and simple single-turn cases continue to use:

```yaml
turns:
  - inbound: "Can you check order 1042?"
```

For `channel: email`, a string `inbound` is treated as the message `body`. The runner supplies `from_address` from the selected `identity_preset`.

### Object form (email)

Email scenarios may use:

```yaml
turns:
  - inbound:
      body: "Can you check order 1042 and invoice INV-9001?"
      subject: "Account inquiry"
```

Optional object fields:

| Field | Use |
|-------|-----|
| `subject` | Inbound email subject line for realistic B2B fixtures |
| `thread_id` | Long-lived **Email Thread** continuity when a scenario needs prior context |
| `message_id` | Distinct inbound message identity within a thread |
| `reply_to` | Alternate reply address for scenario 23; must not affect **Email Sender Match** |

`from_address` is not set per turn by default. The runner resolves it from `identity_preset` unless scenario `mock_overrides` replaces the authenticated **From** identity.

## Runner normalization

Before agent execution, the runner maps each turn to an eval ingress payload:

- string `inbound` → `{ body: <string> }`
- object `inbound` → requires `body`; copies optional envelope fields when present
- merges `from_address` from the resolved identity preset when not overridden

**Email Sender Match** uses only the authenticated **From** address from the preset or override. `reply_to` and body-supplied alternate addresses are message content only, per ADR-0054.

## Scenario 23 pattern

Scenario 23 uses `identity_preset: email_verified_a` and supplies a different `reply_to` or body-requested alternate address at the turn level:

```yaml
turns:
  - inbound:
      body: "Please send the payment link to billing@other-company.example instead."
      subject: "Payment link request"
      reply_to: "billing@other-company.example"
```

Assertions expect a **Follow-up Case** without re-verifying against the alternate address.

**Considered options:** require full **InboundChannelEvent** schema in every email turn (rejected—too heavy for fixture authoring); keep `inbound` as body-only strings and move all envelope fields to scenario-level metadata (rejected—scenario 23 needs turn-level `reply_to`); break SMS fixtures by requiring object-only turns (rejected—backward compatibility requirement).

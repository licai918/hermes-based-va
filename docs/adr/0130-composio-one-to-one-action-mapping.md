# One-to-one Composio mapping behind v1 Domain Adapter actions

Layer 1 **Domain Adapter Tools** that use Composio internally must preserve the public v1 `action` enums from ADR-0059 and ADR-0070. Composio toolkit actions are implementation details mapped inside adapter code.

## Mapping rule

Each v1 `action` maps to at most one Composio toolkit invocation per adapter call.

The adapter sequence for a governed action is:

1. validate profile, identity, and **Tool Gate** rules for the requested v1 `action`
2. invoke one Composio toolkit action with the Connected Account entity reference from ADR-0129
3. transform the Composio response into the Toee response shape expected by Skills, eval fixtures, and workbench consumers
4. write audit metadata using the v1 tool name and `action`, not the Composio action name

## No multi-call orchestration in v1 public actions

A single v1 `action` must not orchestrate multiple Composio toolkit calls in v1 Text-First Launch adapters.

If Composio does not expose one toolkit action that can satisfy a required v1 `action`, that action uses direct REST in the adapter implementation instead. The team does not add a second public `action`, a free-form vendor parameter, or a `composio_action` argument to compensate.

Pagination, field selection, and minor response normalization inside one Composio call are allowed. Separate vendor lookups that change governance boundaries are not.

## Examples

| v1 tool.action | Composio usage |
|----------------|----------------|
| `toee_shopify_read.get_order` | one Shopify order-read toolkit action |
| `toee_shopify_read.search_products` | one Shopify product-search toolkit action |
| `toee_qbo_read.get_invoice` | one QuickBooks invoice-read toolkit action |
| `toee_square_payment_link.send_payment_link` | one Square payment-link toolkit action |

## Eval and mock stability

**Launch Eval** and adapter unit tests mock at the `toee_*` action boundary. They do not assert Composio toolkit names or parameters.

## Future exceptions

A future ADR may allow one-to-many Composio orchestration for a new governed action only when:

- the public v1 `action` semantics require composed vendor reads
- **Tool Gate** still has one public entry point
- the exception is documented with eval coverage

v1 Text-First Launch does not use this exception path.

**Considered options:** map one v1 action to many Composio calls by default (rejected—blurs Tool Gate and complicates mocks); expose `composio_action` to the model (rejected—widens the agent tool surface); rename v1 actions to match Composio schemas (rejected—breaks ADR-0070 and existing eval fixtures).

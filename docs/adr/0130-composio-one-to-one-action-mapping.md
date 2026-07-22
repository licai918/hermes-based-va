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
| `toee_square_payment_link.send_payment_link` | one Square payment-link toolkit action — **does not exist, see the correction below** |

> **Correction (0.0.4 S12, 2026-07-22).** The last row was never true. Composio's
> Square toolkit exposes **no create-payment-link action at any version**: the live
> surface probe found only `SQUARE_RETRIEVE_PAYMENT_LINK` at pin `20260616_00`, the
> previously mapped `SQUARE_CREATE_PAYMENT_LINK` 404s at `latest` too, and a
> catalog-wide search returns a create action for Flutterwave, Razorpay, Stripe and
> Poof but not Square. `toee_square_payment_link.send_payment_link` therefore fails
> closed on the Composio backend (`ActionSpec.unavailable`) rather than mapping to
> anything.
>
> The mapping RULE this ADR decides is unaffected — this records a fact about the
> vendor, not a change of decision. The ADR's own escape hatch ("if Composio does
> not expose one toolkit action that can satisfy a required v1 `action`, that action
> uses direct REST in the adapter implementation instead") is the path this gap
> would take. **Which path to take is the owner's product decision and is still
> pending**; nothing is decided here.

## Eval and mock stability

**Launch Eval** and adapter unit tests mock at the `toee_*` action boundary. They do not assert Composio toolkit names or parameters.

## Future exceptions

A future ADR may allow one-to-many Composio orchestration for a new governed action only when:

- the public v1 `action` semantics require composed vendor reads
- **Tool Gate** still has one public entry point
- the exception is documented with eval coverage

v1 Text-First Launch does not use this exception path.

**Considered options:** map one v1 action to many Composio calls by default (rejected—blurs Tool Gate and complicates mocks); expose `composio_action` to the model (rejected—widens the agent tool surface); rename v1 actions to match Composio schemas (rejected—breaks ADR-0070 and existing eval fixtures).

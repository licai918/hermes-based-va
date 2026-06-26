# Product Media Reply for public catalog without verified identity

When a customer requests a product image over Textline SMS, Hermes may send a **Product Media Reply** through a live Shopify Tool read and the Textline Tool in the **current SMS Session**. **Phone Match Verification** is not required for public catalog media.

**Unmatched Caller** and **Verified Customer** may both receive **Product Media Reply** for publicly listed Shopify products. An **Unmatched Caller** reply must not include account-scoped facts such as customer-specific pricing, contract pricing, live inventory, or order or invoice context.

A **Verified Customer** may receive live price and inventory in the **same Product Media Reply** message as the product image or link when the customer asks for them. Price and inventory must come from the same live Shopify Tool read, not from RAG or weekly sync cache.

A **Verified Customer** may refer to a **Prior Order Product Reference** such as "the one I ordered last time." Hermes may resolve that phrase through live Shopify order history only when the most recent qualifying order line item uniquely identifies one product. If multiple recent orders or line items could match, Hermes asks for disambiguation such as order number, invoice number, or size before sending media. An **Unmatched Caller** may not use prior-order references; Hermes asks for public product details or creates a **Follow-up Case**.

Hermes resolves one product per reply. If the request matches multiple products, Hermes asks for disambiguation such as size, SKU, or brand before sending media.

**Delivery format:** Hermes sends one primary product image when Textline MMS is available, with optional brief live price and inventory text in the same SMS when the caller is a **Verified Customer**. If MMS is unavailable or fails, Hermes falls back to an approved public product page link in the same SMS thread. Hermes does not send media to a new phone number or email supplied in the message body.

**Source rule:** image URLs, product links, price, and inventory must come from live Shopify Tool reads. Hermes does not use RAG, weekly sync cache, or fabricated URLs. If Shopify is unavailable, Hermes uses a **Tool Unavailable Response** and creates a **Follow-up Case**.

**Considered options:** require **Verified Customer** for all product images (rejected—public catalog media is not account disclosure); send multiple product images in one reply (rejected—SMS clarity and MMS limits); use cached weekly sync images (rejected—live media rule from ADR-0031); split verified price/inventory into a separate follow-up message only (rejected—user chose same-message live facts for verified callers); auto-resolve "last ordered" from any historical order without uniqueness check (rejected—ambiguous recent orders need disambiguation); require explicit SKU even for verified callers (rejected—unique recent order reference is safe enough).

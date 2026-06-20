# Domain adapter tools use one tool per integration with action enums

Toee Tire **Domain Adapter Tools** register one Hermes tool per business integration domain and expose v1 behavior through a required `action` parameter with a fixed enum per tool. Examples include `toee_shopify_read` with actions such as `get_order` and `search_products`, rather than registering a separate Hermes tool for every operation.

**Tool Gate** checks run inside adapter code against the requested `action`, active **Hermes Profile**, and current identity snapshot. **Profile Tool Allowlist** still controls which tool names are callable; `action` controls which operation inside that tool is permitted.

**Considered options:** register one Hermes tool per operation (rejected—allowlist and audit surface grow too fast); use free-form query parameters without action enums (rejected—weak enforcement and harder eval assertions); implement integrations only as Skills without tools (rejected—no programmatic gate).

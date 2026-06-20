# Tool failure responses without fabricated facts

When a real-time business tool such as Shopify, QBO, Square, or EasyRoutes fails with timeout or retryable server errors, Hermes must not guess or use RAG as a substitute for live facts.

For customer-facing SMS and other external channels, Hermes sends a brief English explanation that the requested system is temporarily unavailable, creates a **Follow-up Case** tagged such as `tool_unavailable`, and records the failed tool name and error class for **Copilot Workbench** review.

Hermes does not present knowledge-base content as if it were a live order, accounting, delivery, or payment status read.

**Considered options:** silent failure with generic apology only (rejected—no case trail); retry indefinitely before replying (rejected—poor SMS latency).

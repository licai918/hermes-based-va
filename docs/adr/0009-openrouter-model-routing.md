# OpenRouter primary and fallback models for Hermes text core

Hermes text core routes chat completions through OpenRouter with a fixed two-model policy for the phone MVP and shared text orchestration.

| Role | OpenRouter model slug | Use |
|------|----------------------|-----|
| Primary | `deepseek/deepseek-v4-pro` | Default conversation, tool planning, and customer-facing text generation |
| Fallback | `qwen/qwen3.6-flash` | Used when the primary model returns retryable errors (429/5xx) or is unavailable |

Model slugs are pinned per environment. Changing primary or fallback models requires running the Hermes eval gate (accounting, orders, refunds, delivery, overreach, prompt injection).

For phone latency, the primary model should use a non-max reasoning setting where supported; fallback is optimized for speed when the primary path fails.

STT/TTS remain on Twilio ConversationRelay and are not routed through OpenRouter in the first version.

**Considered options:** GPT-4.1-mini / Claude Sonnet as defaults (rejected—operator preference for DeepSeek primary and Qwen fallback on OpenRouter).

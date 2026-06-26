// Per-phone soft inbound rate limiter (ADR-0109). v1 tracks accepted inbound
// volume by normalized fromPhone over a sliding window of ten messages per
// minute. When a sender exceeds the limit the gateway still persists the turn
// and returns 200, but skips async job enqueue; this limiter only renders the
// allow/limit decision and the route layer applies that behavior.
export interface InboundRateLimiterOptions {
  limit?: number;
  windowMs?: number;
}

export interface RateLimitDecision {
  allowed: boolean;
  /** Count of in-window hits already recorded for the sender. */
  count: number;
}

export interface InboundRateLimiter {
  check(fromPhone: string, atMs?: number): RateLimitDecision;
}

export function createInboundRateLimiter(
  options: InboundRateLimiterOptions = {}
): InboundRateLimiter {
  const limit = options.limit ?? 10;
  const windowMs = options.windowMs ?? 60_000;
  const hits = new Map<string, number[]>();

  return {
    check(fromPhone: string, atMs?: number): RateLimitDecision {
      const now = atMs ?? Date.now();
      const recent = (hits.get(fromPhone) ?? []).filter((t) => now - t < windowMs);
      if (recent.length >= limit) {
        hits.set(fromPhone, recent);
        return { allowed: false, count: recent.length };
      }
      recent.push(now);
      hits.set(fromPhone, recent);
      return { allowed: true, count: recent.length };
    },
  };
}

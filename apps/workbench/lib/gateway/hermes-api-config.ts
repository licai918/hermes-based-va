// Per-profile Hermes API config resolution (ADR-0141). Pure like
// session-secret.ts: callers pass the raw env values so this stays unit-testable
// and runtime-agnostic. Both a base URL and a token must be present; otherwise the
// BFF falls back to the in-memory store, so local dev and tests run without the
// per-profile backend wired.
export interface ProfileApiConfig {
  baseUrl: string;
  token: string;
}

export function resolveProfileApiConfig(
  url: string | undefined,
  token: string | undefined,
): ProfileApiConfig | null {
  if (url && url.length > 0 && token && token.length > 0) {
    return { baseUrl: url, token };
  }
  return null;
}

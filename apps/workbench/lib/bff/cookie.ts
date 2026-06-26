// Set-Cookie builders for the workbench session (ADR-0093). HttpOnly + SameSite=Lax
// + Path=/, plus Secure in production. Kept tiny and string-based so it works in
// both Node route handlers and Edge without next/headers.
import { SESSION_COOKIE_NAME } from "../auth/session";

export function buildSessionCookie(
  token: string,
  opts: { maxAgeSeconds: number; secure: boolean },
): string {
  const parts = [
    `${SESSION_COOKIE_NAME}=${token}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${opts.maxAgeSeconds}`,
  ];
  if (opts.secure) parts.push("Secure");
  return parts.join("; ");
}

export function buildClearedSessionCookie(opts: { secure: boolean }): string {
  const parts = [
    `${SESSION_COOKIE_NAME}=`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    "Max-Age=0",
  ];
  if (opts.secure) parts.push("Secure");
  return parts.join("; ");
}

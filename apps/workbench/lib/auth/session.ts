// Signed workbench session token (ADR-0018 idle timeout, ADR-0093 cookie name).
// EDGE-SAFE: runs in both Next middleware (Edge runtime) and Node route handlers.
// Uses ONLY Web Crypto (globalThis.crypto.subtle), TextEncoder/TextDecoder and
// base64url. Do NOT import node:crypto or any Node-only API here.
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";

export const SESSION_COOKIE_NAME = "workbench_session";
export const SESSION_IDLE_MS = 8 * 60 * 60 * 1000;

export type WorkbenchSession = {
  accountId: string;
  username: string;
  role: WorkbenchRoleId;
  lastActivityAt: number;
};

const ROLE_VALUES = new Set<string>(Object.values(WORKBENCH_ROLES));
const encoder = new TextEncoder();
const decoder = new TextDecoder();

function base64urlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64urlDecode(value: string): Uint8Array {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function hmac(payloadB64: string, secret: string): Promise<Uint8Array> {
  const key = await globalThis.crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await globalThis.crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(payloadB64),
  );
  return new Uint8Array(signature);
}

function timingSafeEqualBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}

function isWorkbenchSession(value: unknown): value is WorkbenchSession {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.accountId === "string" &&
    typeof record.username === "string" &&
    typeof record.role === "string" &&
    ROLE_VALUES.has(record.role) &&
    typeof record.lastActivityAt === "number" &&
    Number.isFinite(record.lastActivityAt)
  );
}

export async function createSessionToken(
  session: WorkbenchSession,
  secret: string,
): Promise<string> {
  const payloadB64 = base64urlEncode(encoder.encode(JSON.stringify(session)));
  const signatureB64 = base64urlEncode(await hmac(payloadB64, secret));
  return `${payloadB64}.${signatureB64}`;
}

export async function verifySessionToken(
  token: string,
  secret: string,
): Promise<WorkbenchSession | null> {
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const [payloadB64, signatureB64] = parts;
  if (!payloadB64 || !signatureB64) return null;

  let expected: Uint8Array;
  let provided: Uint8Array;
  try {
    expected = await hmac(payloadB64, secret);
    provided = base64urlDecode(signatureB64);
  } catch {
    return null;
  }
  if (!timingSafeEqualBytes(expected, provided)) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(decoder.decode(base64urlDecode(payloadB64)));
  } catch {
    return null;
  }
  return isWorkbenchSession(parsed) ? parsed : null;
}

// Pure idle-timeout check (ADR-0018). Kept separate from verify so the clock is
// never baked into signature verification.
export function isSessionExpired(
  session: WorkbenchSession,
  now: number,
): boolean {
  return now - session.lastActivityAt > SESSION_IDLE_MS;
}

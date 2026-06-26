// Workbench password policy + hashing (ADR-0018). Node runtime ONLY — uses
// node:crypto. Do not import this module from Edge code (middleware).
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

const MIN_LENGTH = 12;
const SALT_BYTES = 16;
const KEY_BYTES = 64;
const HEX = /^[0-9a-f]+$/i;

export function validatePassword(
  password: string,
): { ok: true } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  if (password.length < MIN_LENGTH) {
    errors.push(`Password must be at least ${MIN_LENGTH} characters long.`);
  }
  if (!/[A-Z]/.test(password)) {
    errors.push("Password must contain at least one uppercase letter.");
  }
  if (!/[a-z]/.test(password)) {
    errors.push("Password must contain at least one lowercase letter.");
  }
  if (!/[0-9]/.test(password)) {
    errors.push("Password must contain at least one digit.");
  }
  return errors.length === 0 ? { ok: true } : { ok: false, errors };
}

export function hashPassword(plain: string): string {
  const salt = randomBytes(SALT_BYTES);
  const hash = scryptSync(plain, salt, KEY_BYTES);
  return `scrypt$${salt.toString("hex")}$${hash.toString("hex")}`;
}

export function verifyPassword(plain: string, stored: string): boolean {
  const parts = stored.split("$");
  if (parts.length !== 3) return false;
  const [scheme, saltHex, hashHex] = parts;
  if (scheme !== "scrypt" || !saltHex || !hashHex) return false;
  if (!HEX.test(saltHex) || !HEX.test(hashHex)) return false;
  if (saltHex.length % 2 !== 0 || hashHex.length % 2 !== 0) return false;
  try {
    const salt = Buffer.from(saltHex, "hex");
    const expected = Buffer.from(hashHex, "hex");
    if (salt.length === 0 || expected.length === 0) return false;
    const actual = scryptSync(plain, salt, expected.length);
    // actual.length === expected.length by construction; timingSafeEqual still
    // guards against length mismatch from any future change.
    return actual.length === expected.length && timingSafeEqual(actual, expected);
  } catch {
    return false;
  }
}

// Workbench password policy + hashing (ADR-0018). Node runtime ONLY — uses
// node:crypto. Do not import this module from Edge code (middleware).
//
// 0.0.4 S09 deleted `verifyPassword`: the workbench no longer verifies credentials
// in-process, `toee_workbench_admin.authenticate` does. `hashPassword` SURVIVES —
// admin-created accounts are hashed here and only the hash crosses the wire
// (ADR-0144's deliberate design, pinned by a cross-runtime hash-compatibility test
// in hermes-runtime). Both halves must stay scrypt N=16384/r=8/p=1, 64-byte key,
// `scrypt$<saltHex>$<hashHex>` — the Python side parses exactly this format.
import { randomBytes, scryptSync } from "node:crypto";

const MIN_LENGTH = 12;
const SALT_BYTES = 16;
const KEY_BYTES = 64;

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

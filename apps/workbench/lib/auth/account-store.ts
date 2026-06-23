// In-memory workbench account store (ADR-0018 lockout policy). STUB SEAM: Slice 3
// replaces createInMemoryAccountStore with a Postgres-backed AccountStore; keep
// this interface stable. Node runtime only (hashes via password.ts / node:crypto).
import { randomUUID } from "node:crypto";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import { hashPassword } from "./password";

export const MAX_FAILED_ATTEMPTS = 5;
export const LOCKOUT_MS = 15 * 60 * 1000;
export const DEV_SEED_PASSWORD = "Workbench123!";

export type WorkbenchAccount = {
  accountId: string;
  username: string;
  role: WorkbenchRoleId;
  status: "active" | "disabled";
  passwordHash: string;
  lastLoginAt: number | null;
  createdAt: number;
  failedAttempts: number;
  lockedUntil: number | null;
};

export interface AccountStore {
  getByUsername(username: string): WorkbenchAccount | undefined;
  getById(accountId: string): WorkbenchAccount | undefined;
  list(): WorkbenchAccount[];
  create(
    input: { username: string; role: WorkbenchRoleId; password: string },
    now: number,
  ): WorkbenchAccount;
  updateRole(
    accountId: string,
    role: WorkbenchRoleId,
  ): WorkbenchAccount | undefined;
  disable(accountId: string): WorkbenchAccount | undefined;
  recordFailedLogin(accountId: string, now: number): void;
  recordSuccessfulLogin(accountId: string, now: number): void;
  isLocked(account: WorkbenchAccount, now: number): boolean;
}

const SEED_ACCOUNTS: ReadonlyArray<{
  accountId: string;
  username: string;
  role: WorkbenchRoleId;
}> = [
  { accountId: "seed-rep", username: "rep", role: WORKBENCH_ROLES.rep },
  {
    accountId: "seed-supervisor",
    username: "supervisor",
    role: WORKBENCH_ROLES.supervisor,
  },
  { accountId: "seed-admin", username: "admin", role: WORKBENCH_ROLES.admin },
];

export function createInMemoryAccountStore(seededAt = 0): AccountStore {
  const byId = new Map<string, WorkbenchAccount>();
  const idByUsername = new Map<string, string>();

  function insert(account: WorkbenchAccount): WorkbenchAccount {
    byId.set(account.accountId, account);
    idByUsername.set(account.username, account.accountId);
    return account;
  }

  for (const seed of SEED_ACCOUNTS) {
    insert({
      accountId: seed.accountId,
      username: seed.username,
      role: seed.role,
      status: "active",
      passwordHash: hashPassword(DEV_SEED_PASSWORD),
      lastLoginAt: null,
      createdAt: seededAt,
      failedAttempts: 0,
      lockedUntil: null,
    });
  }

  return {
    getByUsername(username) {
      const id = idByUsername.get(username);
      return id === undefined ? undefined : byId.get(id);
    },
    getById(accountId) {
      return byId.get(accountId);
    },
    list() {
      return [...byId.values()];
    },
    create(input, now) {
      if (idByUsername.has(input.username)) {
        throw new Error(`username already exists: ${input.username}`);
      }
      return insert({
        accountId: randomUUID(),
        username: input.username,
        role: input.role,
        status: "active",
        passwordHash: hashPassword(input.password),
        lastLoginAt: null,
        createdAt: now,
        failedAttempts: 0,
        lockedUntil: null,
      });
    },
    updateRole(accountId, role) {
      const account = byId.get(accountId);
      if (!account) return undefined;
      account.role = role;
      return account;
    },
    disable(accountId) {
      const account = byId.get(accountId);
      if (!account) return undefined;
      account.status = "disabled";
      return account;
    },
    recordFailedLogin(accountId, now) {
      const account = byId.get(accountId);
      if (!account) return;
      account.failedAttempts += 1;
      if (account.failedAttempts >= MAX_FAILED_ATTEMPTS) {
        account.lockedUntil = now + LOCKOUT_MS;
        account.failedAttempts = 0;
      }
    },
    recordSuccessfulLogin(accountId, now) {
      const account = byId.get(accountId);
      if (!account) return;
      account.lastLoginAt = now;
      account.failedAttempts = 0;
      account.lockedUntil = null;
    },
    isLocked(account, now) {
      return account.lockedUntil !== null && now < account.lockedUntil;
    },
  };
}

// Process-wide singleton used by the BFF / login route so account state (lockouts,
// created accounts) persists across requests in dev. Tests build their own store
// via createInMemoryAccountStore instead of touching this.
let singleton: AccountStore | undefined;

export function getAccountStore(): AccountStore {
  if (!singleton) singleton = createInMemoryAccountStore(Date.now());
  return singleton;
}

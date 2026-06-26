import { describe, expect, it } from "vitest";
import { WORKBENCH_ROLES } from "@toee/shared";
import { verifyPassword } from "./password";
import {
  createInMemoryAccountStore,
  DEV_SEED_PASSWORD,
  getAccountStore,
  LOCKOUT_MS,
  MAX_FAILED_ATTEMPTS,
} from "./account-store";

describe("constants (ADR-0018)", () => {
  it("exposes the lockout policy constants", () => {
    expect(MAX_FAILED_ATTEMPTS).toBe(5);
    expect(LOCKOUT_MS).toBe(15 * 60 * 1000);
  });
});

describe("seed", () => {
  it("seeds one account per role whose DEV_SEED_PASSWORD verifies", () => {
    const store = createInMemoryAccountStore(0);
    const rep = store.getByUsername("rep");
    const supervisor = store.getByUsername("supervisor");
    const admin = store.getByUsername("admin");
    expect(rep?.role).toBe(WORKBENCH_ROLES.rep);
    expect(supervisor?.role).toBe(WORKBENCH_ROLES.supervisor);
    expect(admin?.role).toBe(WORKBENCH_ROLES.admin);
    for (const account of [rep, supervisor, admin]) {
      expect(account).toBeDefined();
      expect(verifyPassword(DEV_SEED_PASSWORD, account!.passwordHash)).toBe(
        true,
      );
      expect(account!.status).toBe("active");
      expect(account!.createdAt).toBe(0);
      expect(account!.lastLoginAt).toBeNull();
    }
  });

  it("list() returns all seeded accounts", () => {
    expect(createInMemoryAccountStore(0).list().length).toBe(3);
  });
});

describe("getById / getByUsername", () => {
  it("resolves by id and username, undefined otherwise", () => {
    const store = createInMemoryAccountStore(0);
    const rep = store.getByUsername("rep");
    expect(rep).toBeDefined();
    expect(store.getById(rep!.accountId)).toBe(rep);
    expect(store.getByUsername("nobody")).toBeUndefined();
    expect(store.getById("nobody")).toBeUndefined();
  });
});

describe("create", () => {
  it("hashes the password so a subsequent login verifies", () => {
    const store = createInMemoryAccountStore(0);
    const created = store.create(
      { username: "newrep", role: WORKBENCH_ROLES.rep, password: "BrandNew123" },
      1234,
    );
    expect(created.username).toBe("newrep");
    expect(created.role).toBe(WORKBENCH_ROLES.rep);
    expect(created.createdAt).toBe(1234);
    expect(created.passwordHash).not.toContain("BrandNew123");
    const fetched = store.getByUsername("newrep");
    expect(verifyPassword("BrandNew123", fetched!.passwordHash)).toBe(true);
  });

  it("throws on a duplicate username", () => {
    const store = createInMemoryAccountStore(0);
    expect(() =>
      store.create(
        { username: "rep", role: WORKBENCH_ROLES.rep, password: "Whatever123" },
        1,
      ),
    ).toThrow();
  });
});

describe("lockout (ADR-0018)", () => {
  it("locks after 5 failures for 15 min and unlocks after the window", () => {
    const store = createInMemoryAccountStore(0);
    const rep = store.getByUsername("rep")!;
    const start = 10_000;
    for (let i = 0; i < MAX_FAILED_ATTEMPTS; i++) {
      expect(store.isLocked(rep, start)).toBe(false);
      store.recordFailedLogin(rep.accountId, start);
    }
    expect(rep.lockedUntil).toBe(start + LOCKOUT_MS);
    expect(rep.failedAttempts).toBe(0);
    expect(store.isLocked(rep, start)).toBe(true);
    expect(store.isLocked(rep, start + LOCKOUT_MS - 1)).toBe(true);
    expect(store.isLocked(rep, start + LOCKOUT_MS)).toBe(false);
    expect(store.isLocked(rep, start + LOCKOUT_MS + 1)).toBe(false);
  });

  it("recordSuccessfulLogin clears the lock and sets lastLoginAt", () => {
    const store = createInMemoryAccountStore(0);
    const rep = store.getByUsername("rep")!;
    for (let i = 0; i < MAX_FAILED_ATTEMPTS; i++) {
      store.recordFailedLogin(rep.accountId, 0);
    }
    expect(rep.lockedUntil).not.toBeNull();
    store.recordSuccessfulLogin(rep.accountId, 5555);
    expect(rep.lockedUntil).toBeNull();
    expect(rep.failedAttempts).toBe(0);
    expect(rep.lastLoginAt).toBe(5555);
  });
});

describe("updateRole / disable", () => {
  it("mutates role and status, returning undefined for unknown ids", () => {
    const store = createInMemoryAccountStore(0);
    const rep = store.getByUsername("rep")!;
    expect(store.updateRole(rep.accountId, WORKBENCH_ROLES.supervisor)?.role).toBe(
      WORKBENCH_ROLES.supervisor,
    );
    expect(store.getById(rep.accountId)?.role).toBe(WORKBENCH_ROLES.supervisor);
    expect(store.disable(rep.accountId)?.status).toBe("disabled");
    expect(store.getById(rep.accountId)?.status).toBe("disabled");
    expect(store.updateRole("nobody", WORKBENCH_ROLES.admin)).toBeUndefined();
    expect(store.disable("nobody")).toBeUndefined();
  });
});

describe("getAccountStore singleton", () => {
  it("returns a stable, seeded process-wide store", () => {
    const a = getAccountStore();
    const b = getAccountStore();
    expect(a).toBe(b);
    expect(a.getByUsername("admin")?.role).toBe(WORKBENCH_ROLES.admin);
  });
});

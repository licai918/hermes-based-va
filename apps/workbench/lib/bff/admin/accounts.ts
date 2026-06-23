// Account-management handlers for the Admin BFF (ADR-0089 user admin; ADR-0018
// password policy + lockout). Pure and dependency-injected; the thin
// app/api/admin/accounts route files wrap these with withSession and inject the
// real AccountStore singleton.
//
// SECURITY: responses NEVER serialize passwordHash (or lockout internals). Every
// account leaves the server through toPublicAccount, which whitelists fields —
// do not spread a WorkbenchAccount onto the wire.
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import type { WorkbenchAccount } from "../../auth/account-store";
import { validatePassword } from "../../auth/password";
import { json, problem } from "../respond";
import { type AdminDeps, readJsonBody } from "./deps";

export type PublicAccount = {
  accountId: string;
  username: string;
  role: WorkbenchRoleId;
  status: WorkbenchAccount["status"];
  lastLoginAt: number | null;
  createdAt: number;
};

const ROLE_VALUES = new Set<string>(Object.values(WORKBENCH_ROLES));

function isValidRole(value: unknown): value is WorkbenchRoleId {
  return typeof value === "string" && ROLE_VALUES.has(value);
}

// Whitelist projection: the only shape safe to put on the wire.
export function toPublicAccount(account: WorkbenchAccount): PublicAccount {
  return {
    accountId: account.accountId,
    username: account.username,
    role: account.role,
    status: account.status,
    lastLoginAt: account.lastLoginAt,
    createdAt: account.createdAt,
  };
}

export function handleListAccounts(deps: AdminDeps): Response {
  return json({ accounts: deps.accounts.list().map(toPublicAccount) });
}

export async function handleCreateAccount(
  req: Request,
  deps: AdminDeps,
): Promise<Response> {
  const body = await readJsonBody(req);
  const username = body?.username;
  const role = body?.role;
  const password = body?.password;
  if (
    typeof username !== "string" ||
    username.length === 0 ||
    typeof password !== "string" ||
    password.length === 0 ||
    typeof role !== "string" ||
    role.length === 0
  ) {
    return problem(400, "username, role, and password are required");
  }
  if (!isValidRole(role)) return problem(400, "invalid role");

  const policy = validatePassword(password);
  if (!policy.ok) {
    return problem(400, "password does not meet policy", {
      errors: policy.errors,
    });
  }

  try {
    const created = deps.accounts.create({ username, role, password }, deps.now);
    return json({ account: toPublicAccount(created) }, { status: 201 });
  } catch {
    return problem(409, "username already exists");
  }
}

export async function handleUpdateRole(
  req: Request,
  accountId: string,
  deps: AdminDeps,
): Promise<Response> {
  const body = await readJsonBody(req);
  const role = body?.role;
  if (!isValidRole(role)) return problem(400, "invalid role");

  const updated = deps.accounts.updateRole(accountId, role);
  if (!updated) return problem(404, "account not found");
  return json({ account: toPublicAccount(updated) });
}

export function handleDisableAccount(
  accountId: string,
  deps: AdminDeps,
): Response {
  const disabled = deps.accounts.disable(accountId);
  if (!disabled) return problem(404, "account not found");
  return json({ account: toPublicAccount(disabled) });
}

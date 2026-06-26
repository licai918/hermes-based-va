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
import { hashPassword, validatePassword } from "../../auth/password";
import { HermesApiClient, HermesApiError } from "../../gateway/hermes-api-client";
import { hermesErrorToProblem } from "../../gateway/hermes-error";
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

const STATUS_VALUES = new Set<string>(["active", "disabled"]);

function isoToMs(value: unknown, label: string): number {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const ms = Date.parse(value);
    if (!Number.isNaN(ms)) return ms;
  }
  throw new HermesApiError("unexpected_error", `malformed account ${label}`);
}

// workbench_account has no last-login column yet (login is not cut over); a value
// is mapped if present, else null — the same null a freshly created store account has.
function optionalMs(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.length > 0) {
    const ms = Date.parse(value);
    if (!Number.isNaN(ms)) return ms;
  }
  return null;
}

// Maps a snake_case workbench_account row from the per-profile API (ADR-0141) onto
// the wire-safe PublicAccount, rejecting contract violations (unknown role/status,
// malformed timestamp) as governed HermesApiErrors so a bad upstream surfaces on
// the ADR-0090 banner instead of rendering garbage (mirrors hermes-map.ts). The
// datastore never returns password_hash, and this whitelist would drop it anyway.
export function mapPublicAccount(raw: unknown): PublicAccount {
  if (typeof raw !== "object" || raw === null) {
    throw new HermesApiError("unexpected_error", "malformed account payload");
  }
  const r = raw as Record<string, unknown>;
  const accountId =
    (typeof r.account_id === "string" && r.account_id) ||
    (typeof r.id === "string" && r.id) ||
    "";
  if (!accountId) throw new HermesApiError("unexpected_error", "missing account id");
  if (typeof r.username !== "string" || r.username.length === 0) {
    throw new HermesApiError("unexpected_error", "missing account username");
  }
  if (!isValidRole(r.role)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown account role: ${String(r.role)}`,
    );
  }
  if (typeof r.status !== "string" || !STATUS_VALUES.has(r.status)) {
    throw new HermesApiError(
      "unexpected_error",
      `unknown account status: ${String(r.status)}`,
    );
  }
  return {
    accountId,
    username: r.username,
    role: r.role,
    status: r.status as WorkbenchAccount["status"],
    lastLoginAt: optionalMs(r.last_login_at),
    createdAt: isoToMs(r.created_at, "created_at"),
  };
}

export function handleListAccounts(deps: AdminDeps): Response {
  return json({ accounts: deps.accounts.list().map(toPublicAccount) });
}

type CreateAccountInput = {
  username: string;
  role: WorkbenchRoleId;
  password: string;
};

// Body validation shared by the store and per-profile API create paths so they
// can't drift: same required-field, role, and ADR-0018 password-policy gates, all
// before any store write or dispatch. Returns the parsed input or the 400 to send.
function parseCreateAccountInput(
  body: Record<string, unknown> | null,
): { ok: true; value: CreateAccountInput } | { ok: false; res: Response } {
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
    return { ok: false, res: problem(400, "username, role, and password are required") };
  }
  if (!isValidRole(role)) return { ok: false, res: problem(400, "invalid role") };
  const policy = validatePassword(password);
  if (!policy.ok) {
    return {
      ok: false,
      res: problem(400, "password does not meet policy", { errors: policy.errors }),
    };
  }
  return { ok: true, value: { username, role, password } };
}

export async function handleCreateAccount(
  req: Request,
  deps: AdminDeps,
): Promise<Response> {
  const parsed = parseCreateAccountInput(await readJsonBody(req));
  if (!parsed.ok) return parsed.res;

  try {
    const created = deps.accounts.create(parsed.value, deps.now);
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

// --- Per-profile API cutover (ADR-0141 Increment 4) --------------------------
// The Supervisor Admin account routes dispatch toee_workbench_admin over the
// per-profile Hermes API when HERMES_ADMIN_API_URL/TOKEN are configured. Reads use
// dispatch (fail-open); the governed mutations use dispatchWrite, which is
// fail-closed on the acting account baked into the client — so a write can never
// land a NULL-actor audit row (the datastore enforces the same rule). Each
// mutation returns the fresh account read model, mapped onto PublicAccount; the
// per-class error mapping turns a governed conflict/not_found into 409/404.

export async function handleListAccountsViaApi(
  client: HermesApiClient,
): Promise<Response> {
  try {
    const data = (await client.dispatch("toee_workbench_admin", "list_accounts")) as {
      accounts?: unknown;
    };
    const rows = Array.isArray(data?.accounts) ? data.accounts : [];
    return json({ accounts: rows.map(mapPublicAccount) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleCreateAccountViaApi(
  req: Request,
  client: HermesApiClient,
): Promise<Response> {
  // Validate (incl. password policy) before any dispatch — store-path parity, and
  // a 400 never reaches the network.
  const parsed = parseCreateAccountInput(await readJsonBody(req));
  if (!parsed.ok) return parsed.res;
  try {
    // The plaintext password is hashed here (ADR-0018): only the hash crosses the
    // wire, and dispatchWrite refuses without an attributed actor.
    const result = (await client.dispatchWrite(
      "toee_workbench_admin",
      "create_account",
      {
        username: parsed.value.username,
        role: parsed.value.role,
        password_hash: hashPassword(parsed.value.password),
      },
    )) as { account?: unknown };
    return json({ account: mapPublicAccount(result.account) }, { status: 201 });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleUpdateRoleViaApi(
  req: Request,
  client: HermesApiClient,
  accountId: string,
): Promise<Response> {
  const body = await readJsonBody(req);
  const role = body?.role;
  if (!isValidRole(role)) return problem(400, "invalid role");
  try {
    const result = (await client.dispatchWrite(
      "toee_workbench_admin",
      "update_account_role",
      { account_id: accountId, role },
    )) as { account?: unknown };
    return json({ account: mapPublicAccount(result.account) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

export async function handleDisableAccountViaApi(
  client: HermesApiClient,
  accountId: string,
): Promise<Response> {
  try {
    const result = (await client.dispatchWrite(
      "toee_workbench_admin",
      "disable_account",
      { account_id: accountId },
    )) as { account?: unknown };
    return json({ account: mapPublicAccount(result.account) });
  } catch (err) {
    return hermesErrorToProblem(err);
  }
}

"use client";

// Workbench account administration (ADR-0089): a table of accounts with inline
// role changes + disable, plus a create form. Account data arrives as the
// whitelisted PublicAccount (ADR — no passwordHash on the wire), so this view
// literally cannot render secret material. The create form surfaces the ADR-0018
// password-policy errors[] (400) and the duplicate-username 409 inline. Split
// into a pure view + fetching container.
import { type FormEvent, useEffect, useState } from "react";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import { EmptyState } from "@/components/EmptyState";
import { useErrorBanner } from "@/components/shell/error-banner";
import {
  type CreateAccountInput,
  createAccount,
  disableAccount,
  listAccounts,
  updateRole,
} from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import { formatRelativeTime } from "@/lib/format";
import type { PublicAccount } from "@/lib/bff/admin/accounts";
import { roleLabel } from "@/lib/nav";

const ROLE_OPTIONS: WorkbenchRoleId[] = [
  WORKBENCH_ROLES.rep,
  WORKBENCH_ROLES.supervisor,
  WORKBENCH_ROLES.admin,
];

const STATUS_LABELS: Record<PublicAccount["status"], string> = {
  active: "Active",
  disabled: "Disabled",
};

const cellStyle = {
  padding: "0.4rem 0.6rem",
  borderBottom: "1px solid #eee",
  textAlign: "left" as const,
  verticalAlign: "middle" as const,
};

export type AccountsConsoleViewProps = {
  accounts: PublicAccount[];
  now: number;
  busy: boolean;
  createError: string | null;
  createErrors: string[] | null;
  onCreate: (input: CreateAccountInput) => Promise<boolean> | void;
  onChangeRole: (accountId: string, role: WorkbenchRoleId) => void;
  onDisable: (accountId: string) => void;
};

function RoleOptions() {
  return (
    <>
      {ROLE_OPTIONS.map((r) => (
        <option key={r} value={r}>
          {roleLabel(r)}
        </option>
      ))}
    </>
  );
}

export function AccountsConsoleView({
  accounts,
  now,
  busy,
  createError,
  createErrors,
  onCreate,
  onChangeRole,
  onDisable,
}: AccountsConsoleViewProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<WorkbenchRoleId>(WORKBENCH_ROLES.rep);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const ok = await onCreate({ username, role, password });
    if (ok) {
      setUsername("");
      setPassword("");
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {accounts.length === 0 ? (
        <EmptyState title="No accounts yet" description="Create the first workbench account below." />
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={cellStyle}>Username</th>
              <th style={cellStyle}>Role</th>
              <th style={cellStyle}>Status</th>
              <th style={cellStyle}>Last login</th>
              <th style={cellStyle}>Created</th>
              <th style={cellStyle}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => {
              const isDisabled = account.status === "disabled";
              return (
                <tr key={account.accountId}>
                  <td style={cellStyle}>{account.username}</td>
                  <td style={cellStyle}>
                    <select
                      aria-label={`Role for ${account.username}`}
                      value={account.role}
                      disabled={isDisabled}
                      onChange={(e) =>
                        onChangeRole(account.accountId, e.target.value as WorkbenchRoleId)
                      }
                    >
                      <RoleOptions />
                    </select>
                  </td>
                  <td style={cellStyle}>{STATUS_LABELS[account.status]}</td>
                  <td style={cellStyle}>
                    {account.lastLoginAt === null
                      ? "never"
                      : formatRelativeTime(account.lastLoginAt, now)}
                  </td>
                  <td style={cellStyle}>{formatRelativeTime(account.createdAt, now)}</td>
                  <td style={cellStyle}>
                    <button
                      type="button"
                      aria-label={`Disable ${account.username}`}
                      onClick={() => onDisable(account.accountId)}
                      disabled={isDisabled}
                    >
                      Disable
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <form onSubmit={handleSubmit} style={{ maxWidth: "24rem" }}>
        <h2 style={{ fontSize: "1.0625rem", marginTop: 0 }}>Create account</h2>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="new-username" style={{ display: "block", fontWeight: 600 }}>
            Username
          </label>
          <input
            id="new-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </div>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="new-role" style={{ display: "block", fontWeight: 600 }}>
            Role
          </label>
          <select
            id="new-role"
            value={role}
            onChange={(e) => setRole(e.target.value as WorkbenchRoleId)}
            style={{ width: "100%", boxSizing: "border-box" }}
          >
            <RoleOptions />
          </select>
        </div>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="new-password" style={{ display: "block", fontWeight: 600 }}>
            Password
          </label>
          <input
            id="new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
        </div>

        <button type="submit" disabled={busy}>
          Create account
        </button>

        {createError ? (
          <p role="alert" style={{ color: "#8a1c1c", marginBottom: 0 }}>
            {createError}
          </p>
        ) : null}
        {createErrors && createErrors.length > 0 ? (
          <ul role="alert" style={{ color: "#8a1c1c", margin: "0.5rem 0 0" }}>
            {createErrors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        ) : null}
      </form>
    </div>
  );
}

export function AccountsConsole() {
  const { showError } = useErrorBanner();
  const [accounts, setAccounts] = useState<PublicAccount[]>([]);
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createErrors, setCreateErrors] = useState<string[] | null>(null);
  const [now] = useState(() => Date.now());

  function reload() {
    return listAccounts().then(setAccounts);
  }

  useEffect(() => {
    listAccounts()
      .then(setAccounts)
      .catch((e) => {
        showError(e instanceof ApiError ? e.message : "Failed to load accounts");
      });
  }, [showError]);

  async function handleCreate(input: CreateAccountInput): Promise<boolean> {
    setBusy(true);
    setCreateError(null);
    setCreateErrors(null);
    try {
      const result = await createAccount(input);
      if (result.ok) {
        await reload();
        return true;
      }
      setCreateError(result.error);
      setCreateErrors(result.status === 400 ? (result.errors ?? null) : null);
      if (result.status >= 500) showError(result.error);
      return false;
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Failed to create account";
      setCreateError(msg);
      showError(msg);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await reload();
    } catch (e) {
      showError(e instanceof ApiError ? e.message : "Account update failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AccountsConsoleView
      accounts={accounts}
      now={now}
      busy={busy}
      createError={createError}
      createErrors={createErrors}
      onCreate={handleCreate}
      onChangeRole={(accountId, role) => mutate(() => updateRole(accountId, role))}
      onDisable={(accountId) => mutate(() => disableAccount(accountId))}
    />
  );
}

"use client";

// User menu (ADR-0090): signed-in username, current workbench role, and Logout.
// Logout ends the server session then sends the operator back to /login. The
// post-logout navigation is injectable (onSignedOut) so the action is unit-
// testable without a real jsdom navigation.
import { useState } from "react";
import { ROUTES, type WorkbenchRoleId } from "@toee/shared";
import { roleLabel } from "@/lib/nav";

export function UserMenu({
  username,
  role,
  onSignedOut,
}: {
  username: string;
  role: WorkbenchRoleId;
  onSignedOut?: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function handleLogout() {
    setBusy(true);
    try {
      if (typeof fetch === "function") {
        await fetch("/api/auth/logout", { method: "POST" });
      }
    } finally {
      if (onSignedOut) onSignedOut();
      else window.location.assign(ROUTES.login);
    }
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
      <span style={{ fontWeight: 600 }}>{username}</span>
      <span style={{ opacity: 0.7, fontSize: "0.8125rem" }}>{roleLabel(role)}</span>
      <button type="button" onClick={handleLogout} disabled={busy}>
        Logout
      </button>
    </div>
  );
}

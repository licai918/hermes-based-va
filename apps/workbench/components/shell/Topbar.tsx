"use client";

// Role-aware top navigation bar (ADR-0084/0090). Plain anchors (not next/link):
// ADR-0084 keeps Copilot and Admin as distinct profile contexts that are never
// merged into one page, so a full navigation between them is intended. The active
// item is derived from the current pathname (passed in by the shell).
import { type WorkbenchRoleId } from "@toee/shared";
import { navItemsForRole } from "@/lib/nav";
import { UserMenu } from "./UserMenu";

export function Topbar({
  username,
  role,
  pathname,
}: {
  username: string;
  role: WorkbenchRoleId;
  pathname: string;
}) {
  const items = navItemsForRole(role);
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0.5rem 1rem",
        borderBottom: "1px solid #e2e2e2",
      }}
    >
      <nav aria-label="Primary" style={{ display: "flex", gap: "1rem" }}>
        {items.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <a
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              style={{ fontWeight: active ? 700 : 400 }}
            >
              {item.label}
            </a>
          );
        })}
      </nav>
      <UserMenu username={username} role={role} />
    </header>
  );
}

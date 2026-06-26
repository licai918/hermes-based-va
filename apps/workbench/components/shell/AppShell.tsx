"use client";

// Authenticated workbench shell (ADR-0090): role-aware top bar, the global error
// banner below it, the page content, and the idle-timeout modal. The active path
// for nav highlighting comes from usePathname; the server layout supplies the
// session-derived props.
import { usePathname } from "next/navigation";
import { type ReactNode } from "react";
import { type WorkbenchRoleId } from "@toee/shared";
import { ErrorBannerProvider, GlobalErrorBanner } from "./error-banner";
import { IdleTimeoutModal } from "./IdleTimeoutModal";
import { Topbar } from "./Topbar";

export function AppShell({
  username,
  role,
  lastActivityAt,
  children,
}: {
  username: string;
  role: WorkbenchRoleId;
  lastActivityAt: number;
  children: ReactNode;
}) {
  const pathname = usePathname() ?? "";
  return (
    <ErrorBannerProvider>
      <Topbar username={username} role={role} pathname={pathname} />
      <GlobalErrorBanner />
      <main style={{ padding: "1rem" }}>{children}</main>
      <IdleTimeoutModal lastActivityAt={lastActivityAt} />
    </ErrorBannerProvider>
  );
}

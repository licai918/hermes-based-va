import { redirect } from "next/navigation";
import { type ReactNode } from "react";
import { ROUTES } from "@toee/shared";
import { AppShell } from "@/components/shell/AppShell";
import { getServerSession } from "@/lib/auth/current-session";

// Server shell for every authenticated route (ADR-0092). The edge middleware
// already gates access; this re-reads the verified session to drive the shell
// and, as defense in depth, bounces to /login if the cookie is missing here.
export default async function AuthenticatedLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await getServerSession();
  if (!session) redirect(ROUTES.login);

  return (
    <AppShell
      username={session.username}
      role={session.role}
      lastActivityAt={session.lastActivityAt}
    >
      {children}
    </AppShell>
  );
}

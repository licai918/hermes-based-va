// Copilot Workbench default route (ADR-0028/0077). Thin server component: it
// re-reads the verified session (defense in depth behind the edge middleware and
// the authenticated layout) and hands the operator's account + role to the
// client dashboard. The shell already renders the top bar, so this route does
// not.
import { redirect } from "next/navigation";
import { ROUTES } from "@toee/shared";
import { getServerSession } from "@/lib/auth/current-session";
import { CopilotDashboard } from "@/components/copilot/CopilotDashboard";

export default async function CopilotPage() {
  const session = await getServerSession();
  if (!session) redirect(ROUTES.login);

  return <CopilotDashboard accountId={session.accountId} role={session.role} />;
}

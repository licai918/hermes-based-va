// Supervisor read-only Sales-Outreach Audit detail (ADR-0050/0086). Next 16
// route params arrive as a Promise; the client detail fetches the case (which
// records a Workbench Audit Log audit_view entry server-side). The session role
// re-read here (defense in depth behind the edge middleware, which already
// restricts this whole route to supervisor/admin) drives the review bar's
// visibility (0.0.4 S04).
import { getServerSession } from "@/lib/auth/current-session";
import { SalesOutreachDetail } from "@/components/audit/SalesOutreachDetail";

export default async function SalesOutreachCasePage({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = await params;
  const session = await getServerSession();
  return <SalesOutreachDetail caseId={caseId} role={session?.role} />;
}

// Supervisor read-only Sales-Outreach Audit detail (ADR-0050/0086). Next 16
// route params arrive as a Promise; the client detail fetches the case (which
// records a Workbench Audit Log audit_view entry server-side).
import { SalesOutreachDetail } from "@/components/audit/SalesOutreachDetail";

export default async function SalesOutreachCasePage({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = await params;
  return <SalesOutreachDetail caseId={caseId} />;
}

// Supervisor read-only Auto-Handled Audit detail (ADR-0086). Next 16 route
// params arrive as a Promise; the client detail fetches the record (which
// records a Workbench Audit Log audit_view entry server-side).
import { AutoHandledDetail } from "@/components/audit/AutoHandledDetail";

export default async function AutoHandledRecordPage({
  params,
}: {
  params: Promise<{ recordId: string }>;
}) {
  const { recordId } = await params;
  return <AutoHandledDetail recordId={recordId} />;
}

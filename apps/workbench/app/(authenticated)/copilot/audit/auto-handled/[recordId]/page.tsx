// Supervisor read-only Auto-Handled Audit detail (ADR-0086). Next 16 route
// params arrive as a Promise; the client detail fetches the record (which
// records a Workbench Audit Log audit_view entry server-side). The session role
// re-read here (defense in depth behind the edge middleware, which already
// restricts this whole route to supervisor/admin) drives the review bar's
// visibility (0.0.4 S04).
import { getServerSession } from "@/lib/auth/current-session";
import { decodeRouteParam } from "@/lib/route-param";
import { AutoHandledDetail } from "@/components/audit/AutoHandledDetail";

export default async function AutoHandledRecordPage({
  params,
}: {
  params: Promise<{ recordId: string }>;
}) {
  const { recordId } = await params;
  const session = await getServerSession();
  // Real record ids carry `:` and `+` -- see decodeRouteParam for why the raw
  // param cannot be handed on as-is.
  return <AutoHandledDetail recordId={decodeRouteParam(recordId)} role={session?.role} />;
}

// Supervisor read-only Auto-Handled Audit list (ADR-0037/0085). Thin server
// component; the client list fetches the records on mount. Route is gated to
// supervisor/admin by middleware.
import { AutoHandledList } from "@/components/audit/AutoHandledList";

export default function AutoHandledAuditPage() {
  return (
    <section>
      <h1>Auto-handled audit</h1>
      <p>Read-only review of auto-handled conversations (ADR-0037, ADR-0085).</p>
      <AutoHandledList />
    </section>
  );
}

// Supervisor read-only Sales-Outreach Audit list (ADR-0050/0085). Thin server
// component; the client list fetches the cases on mount. Route is gated to
// supervisor/admin by middleware.
import { SalesOutreachList } from "@/components/audit/SalesOutreachList";

export default function SalesOutreachAuditPage() {
  return (
    <section>
      <h1>Sales outreach</h1>
      <p>
        Read-only review of non-customer sales-outreach cases (ADR-0050,
        ADR-0085).
      </p>
      <SalesOutreachList />
    </section>
  );
}

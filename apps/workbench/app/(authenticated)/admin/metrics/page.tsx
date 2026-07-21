import { MetricsPanel } from "@/components/admin/MetricsPanel";

// Thin server shell for the aggregate-metrics admin panel (0.0.3 S26, FR-28),
// mirroring the sibling admin pages (memory-audit/agent-experience/accounts).
// middleware/withSession already gate /admin/* to the supervisor and admin
// roles (ADR-0093).
export default function AdminMetricsPage() {
  return (
    <section>
      <h1>Metrics</h1>
      <MetricsPanel />
    </section>
  );
}

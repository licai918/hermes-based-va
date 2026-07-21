import { RetentionPanel } from "@/components/admin/RetentionPanel";

// Thin server shell for the Customer Memory retention sweep admin panel
// (0.0.3 S28, FR-30), mirroring the sibling admin pages (metrics/memory-audit/
// agent-experience). middleware/withSession already gate /admin/* to the
// supervisor and admin roles (ADR-0093).
export default function AdminRetentionPage() {
  return (
    <section>
      <h1>Retention sweep</h1>
      <RetentionPanel />
    </section>
  );
}

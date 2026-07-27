import { DeadLetterPanel } from "@/components/admin/DeadLetterPanel";

// Thin server shell for the dead-letter operator view (0.0.4 S05, FR-13),
// mirroring the sibling admin pages. middleware/withSession already gate
// /admin/* to the supervisor and admin roles (ADR-0093) -- the right level for
// an operations surface.
export default function AdminDeadLetterPage() {
  return (
    <section>
      <h1>Dead letters</h1>
      <DeadLetterPanel />
    </section>
  );
}

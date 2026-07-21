import { MemoryAuditConsole } from "@/components/admin/MemoryAuditConsole";

// Thin server shell for the Supervisor Memory Audit View (0.0.3 S20, FR-20),
// mirroring the sibling admin pages (accounts/eval/knowledge). The client
// console loads on demand once a case id is entered; middleware/withSession
// already gate /admin/* to the supervisor and admin roles (ADR-0093).
export default function AdminMemoryAuditPage() {
  return (
    <section>
      <h1>Memory Audit</h1>
      <MemoryAuditConsole />
    </section>
  );
}

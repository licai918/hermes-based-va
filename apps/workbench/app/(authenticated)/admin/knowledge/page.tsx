import { KnowledgeConsole } from "@/components/admin/KnowledgeConsole";

// Thin server shell for the KnowledgeOps console (ADR-0087/0003). The client
// console fetches the policy slots on mount; middleware already gates /admin/*.
export default function AdminKnowledgePage() {
  return (
    <section>
      <h1>Knowledge</h1>
      <KnowledgeConsole />
    </section>
  );
}

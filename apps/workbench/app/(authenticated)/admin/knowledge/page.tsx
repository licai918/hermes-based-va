import { CorpusPanel } from "@/components/admin/CorpusPanel";
import { KnowledgeConsole } from "@/components/admin/KnowledgeConsole";

// Thin server shell for the KnowledgeOps console (ADR-0087/0003). The client
// console fetches the policy slots on mount; middleware already gates /admin/*.
// CorpusPanel (S11/FR-6) is a SIBLING section below the policy-slot
// master-detail -- it does not touch KnowledgeConsole.
export default function AdminKnowledgePage() {
  return (
    <section>
      <h1>Knowledge</h1>
      <KnowledgeConsole />
      <CorpusPanel />
    </section>
  );
}

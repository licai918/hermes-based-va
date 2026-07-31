import { LexiconConsole } from "@/components/admin/LexiconConsole";

// Thin server shell for the L7 Semantic Lexicon console (0.0.5 S02, FR-3/FR-8),
// mirroring the sibling admin pages (agent-experience/memory-audit/accounts).
// middleware/withSession already gate /admin/* to the supervisor and admin roles
// (ADR-0093).
export default function AdminLexiconPage() {
  return (
    <section>
      <h1>Semantic Lexicon</h1>
      <LexiconConsole />
    </section>
  );
}

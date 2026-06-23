import { EvalConsole } from "@/components/admin/EvalConsole";

// Thin server shell for the Launch Eval Review console (ADR-0088/0040). The
// client console fetches eval runs on mount; middleware already gates /admin/*.
export default function AdminEvalPage() {
  return (
    <section>
      <h1>Launch Eval Review</h1>
      <EvalConsole />
    </section>
  );
}

import { EvalConsole } from "@/components/admin/EvalConsole";
import { QualityGatesPanel } from "@/components/admin/QualityGatesPanel";

// Thin server shell for the Launch Eval Review console (ADR-0088/0040). The
// client console fetches eval runs on mount; middleware already gates /admin/*.
// QualityGatesPanel (S12, FR-7/FR-7b/FR-29) is a static sibling section --
// the knowledge recall/latency gates and the judge measurement report.
export default function AdminEvalPage() {
  return (
    <section>
      <h1>Launch Eval Review</h1>
      <EvalConsole />
      <QualityGatesPanel />
    </section>
  );
}

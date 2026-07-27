import { EvalConsole } from "@/components/admin/EvalConsole";
import { QualityGatesPanel } from "@/components/admin/QualityGatesPanel";

// Thin server shell for the Launch Eval Review console (ADR-0088/0040). The
// client console fetches eval runs on mount; middleware already gates /admin/*.
// QualityGatesPanel (S12; 0.0.4 S23, FR-32) is a sibling section that reads the
// latest knowledge recall/latency + judge gate-report artifacts live.
export default function AdminEvalPage() {
  return (
    <section>
      <h1>Launch Eval Review</h1>
      <EvalConsole />
      <QualityGatesPanel />
    </section>
  );
}

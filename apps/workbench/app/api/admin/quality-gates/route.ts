import {
  handleGetQualityGates,
  resolveReportsDir,
  resolveStaleThresholdSeconds,
} from "@/lib/bff/admin/quality-gates";
import { withSession } from "@/lib/bff/with-session";

export const runtime = "nodejs";

// FR-32 QualityGatesPanel live read (0.0.4 S23). /api/admin/* is admin-gated by
// withSession (ADR-0093). Reads the newest gate-report artifacts from disk
// (GATE_REPORTS_DIR / repo-root .reports/gates) -- read-only, no Hermes dispatch.
export const GET = withSession(() =>
  handleGetQualityGates(resolveReportsDir(), {
    staleThresholdSeconds: resolveStaleThresholdSeconds(),
  }),
);

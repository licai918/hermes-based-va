import { AgentExperienceConsole } from "@/components/admin/AgentExperienceConsole";

// Thin server shell for the L6 Agent-experience minimal admin list (0.0.3
// S22, FR-23), mirroring the sibling admin pages (memory-audit/accounts/eval).
// middleware/withSession already gate /admin/* to the supervisor and admin
// roles (ADR-0093).
export default function AdminAgentExperiencePage() {
  return (
    <section>
      <h1>Agent Experience</h1>
      <AgentExperienceConsole />
    </section>
  );
}

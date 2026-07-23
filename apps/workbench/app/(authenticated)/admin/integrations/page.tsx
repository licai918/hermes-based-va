import { IntegrationsPanel } from "@/components/admin/IntegrationsPanel";

// Thin server shell for the integrations status page (0.0.4 S15, FR-23). Unlike the
// sibling admin pages (supervisor+admin), this page is ADMIN-ONLY: middleware/
// withSession gate /admin/integrations to the admin role alone (canAccess ->
// requiresAdmin, lib/auth/access.ts), because integrations are a CREDENTIAL surface
// -- deliberately narrower than the dead-letter operations view (gap-review P4).
export default function AdminIntegrationsPage() {
  return (
    <section>
      <h1>Integrations</h1>
      <IntegrationsPanel />
    </section>
  );
}

import { ReviewInbox } from "@/components/admin/ReviewInbox";

// Thin server shell for the unified review inbox (0.0.5 S15, FR-22 / US4 / US9),
// mirroring the sibling admin pages. middleware/withSession already gate
// /admin/* to the supervisor and admin roles (ADR-0093).
export default function AdminInboxPage() {
  return (
    <section>
      <h1>Review Inbox</h1>
      <ReviewInbox />
    </section>
  );
}

"use client";

// Pending proposal list, rendered next to the Customer Preferences panel
// (0.0.3 S15, FR-16). A copilot draft turn may propose one or more Customer
// Memory writes (S14's `proposals[]`, extracted from the governed
// upsert_preference RESULT -- framework-derived, never model-narrated). Each
// renders as a PENDING suggestion with Accept/Dismiss: Accept routes through
// the EXISTING governed dispatch write (upsert_preference, actor-attributed ->
// employee_confirmed -- see CopilotDashboard's onAccept); Dismiss persists no
// slot. A proposal can NEVER auto-accept -- both are reported through
// onAccept/onDismiss so the container (CopilotDashboard) owns the BFF calls,
// mirroring CustomerPreferences' presentational contract.
import type { DraftProposal } from "@/lib/api/copilot-client";
import { SLOT_LABELS } from "./CustomerPreferences";

export function PendingProposals({
  proposals,
  onAccept,
  onDismiss,
}: {
  proposals: DraftProposal[];
  onAccept: (proposal: DraftProposal) => void;
  onDismiss: (proposal: DraftProposal) => void;
}) {
  if (proposals.length === 0) return null;

  return (
    <section
      aria-label="Pending preference proposals"
      style={{ display: "flex", flexDirection: "column", gap: "0.4rem", padding: "0.6rem 0.75rem" }}
    >
      {proposals.map((proposal) => {
        const label = SLOT_LABELS[proposal.slot];
        return (
          <div
            key={proposal.slot}
            style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center", fontSize: "0.85rem" }}
          >
            <span>
              Suggest setting {label} = &quot;{proposal.value}&quot;
            </span>
            <button type="button" aria-label={`Accept ${label} proposal`} onClick={() => onAccept(proposal)}>
              Accept
            </button>
            <button type="button" aria-label={`Dismiss ${label} proposal`} onClick={() => onDismiss(proposal)}>
              Dismiss
            </button>
          </div>
        );
      })}
    </section>
  );
}

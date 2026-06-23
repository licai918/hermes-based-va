"use client";

// Case Queue filter controls (ADR-0079 default filters, ADR-0080 supervisor
// workload filters). Presentational: it renders the current filter and reports
// the next filter upward. Reps see status checkboxes + a narrowed assignee set;
// supervisors/admins additionally get the resolved status and the All team
// assignee option (`canViewAllTeam`).
import type { AssigneeFilterMode, CaseStatus } from "@/lib/gateway/types";

export type QueueFilter = {
  statuses: CaseStatus[];
  assignee: AssigneeFilterMode;
};

const REP_ASSIGNEE_OPTIONS: { mode: AssigneeFilterMode; label: string }[] = [
  { mode: "mine_or_unassigned", label: "Mine or unassigned" },
  { mode: "mine", label: "Mine" },
  { mode: "unassigned", label: "Unassigned" },
];
const ALL_TEAM_OPTION = { mode: "all" as AssigneeFilterMode, label: "All team" };

const STATUS_OPTIONS: { status: CaseStatus; label: string; widened: boolean }[] = [
  { status: "open", label: "Open", widened: false },
  { status: "in_progress", label: "In progress", widened: false },
  { status: "resolved", label: "Resolved", widened: true },
];

export function QueueFilters({
  value,
  onChange,
  canViewAllTeam,
}: {
  value: QueueFilter;
  onChange: (next: QueueFilter) => void;
  canViewAllTeam: boolean;
}) {
  function toggleStatus(status: CaseStatus, checked: boolean) {
    const statuses = checked
      ? [...value.statuses, status]
      : value.statuses.filter((s) => s !== status);
    onChange({ ...value, statuses });
  }

  const assigneeOptions = canViewAllTeam
    ? [...REP_ASSIGNEE_OPTIONS, ALL_TEAM_OPTION]
    : REP_ASSIGNEE_OPTIONS;

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: "1rem",
        padding: "0.5rem 0.6rem",
        borderBottom: "1px solid #e2e2e2",
        fontSize: "0.8125rem",
      }}
    >
      <fieldset
        style={{ display: "flex", gap: "0.75rem", border: "none", padding: 0, margin: 0 }}
      >
        <legend style={{ padding: 0, fontWeight: 600 }}>Status</legend>
        {STATUS_OPTIONS.filter((o) => canViewAllTeam || !o.widened).map((o) => (
          <label key={o.status} style={{ display: "inline-flex", gap: "0.25rem" }}>
            <input
              type="checkbox"
              checked={value.statuses.includes(o.status)}
              onChange={(e) => toggleStatus(o.status, e.target.checked)}
            />
            {o.label}
          </label>
        ))}
      </fieldset>

      <label style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem" }}>
        <span style={{ fontWeight: 600 }}>Assignee</span>
        <select
          aria-label="Assignee"
          value={value.assignee}
          onChange={(e) =>
            onChange({ ...value, assignee: e.target.value as AssigneeFilterMode })
          }
        >
          {assigneeOptions.map((o) => (
            <option key={o.mode} value={o.mode}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

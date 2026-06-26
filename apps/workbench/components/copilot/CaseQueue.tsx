"use client";

// Case Queue zone (ADR-0079 columns + sort, ADR-0080 filters). Presentational:
// it renders the queue filters and a table of CaseRow items in the order the BFF
// returned them (urgent → unassigned → oldest) and reports selection + filter
// changes upward. The container fetches and sorts; this view never reorders.
import type { WorkbenchCase } from "@/lib/gateway/types";
import { CaseRow } from "./CaseRow";
import { QueueFilters, type QueueFilter } from "./QueueFilters";

const HEADERS = [
  "",
  "Channel",
  "Identity",
  "Contact reason",
  "Status",
  "Assignee",
  "Last activity",
  "Last message",
  "",
];

const headerCell: React.CSSProperties = {
  textAlign: "left",
  padding: "0.4rem 0.6rem",
  borderBottom: "2px solid #ddd",
  fontSize: "0.75rem",
  textTransform: "uppercase",
  letterSpacing: "0.03em",
  color: "#666",
};

export function CaseQueue({
  cases,
  accountId,
  selectedCaseId,
  onSelect,
  filter,
  onFilterChange,
  canViewAllTeam,
  now = Date.now(),
  loading = false,
}: {
  cases: WorkbenchCase[];
  accountId: string;
  selectedCaseId: string | null;
  onSelect: (caseId: string) => void;
  filter: QueueFilter;
  onFilterChange: (next: QueueFilter) => void;
  canViewAllTeam: boolean;
  now?: number;
  loading?: boolean;
}) {
  return (
    <section aria-label="Case queue" style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
      <QueueFilters
        value={filter}
        onChange={onFilterChange}
        canViewAllTeam={canViewAllTeam}
      />
      {loading ? (
        <p style={{ padding: "1rem", color: "#666" }}>Loading cases…</p>
      ) : cases.length === 0 ? (
        <p style={{ padding: "1rem", color: "#666" }}>
          No cases match the current filters.
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                {HEADERS.map((label, i) => (
                  <th key={i} scope="col" style={headerCell}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <CaseRow
                  key={c.caseId}
                  case={c}
                  accountId={accountId}
                  selected={c.caseId === selectedCaseId}
                  onSelect={onSelect}
                  now={now}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

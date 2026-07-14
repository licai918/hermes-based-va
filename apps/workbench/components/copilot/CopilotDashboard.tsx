"use client";

// Copilot Workbench dual-zone container (ADR-0028/0077). LEFT: the Case Queue
// with role-aware filters. RIGHT: the selected Case Thread Context (top) over the
// Copilot Gateway (bottom). This is the only stateful, network-touching component
// in the feature — every child is presentational and receives data + callbacks.
// It fetches the queue on mount and on filter change, loads a thread on
// selection, refetches both after any governed mutation, and polls silently
// every few seconds while the tab is visible so inbound SMS updates appear
// without a manual refresh.
import { useCallback, useEffect, useState } from "react";
import { WORKBENCH_ROLES, type WorkbenchRoleId } from "@toee/shared";
import * as copilot from "@/lib/api/copilot-client";
import type { DraftKind } from "@/lib/api/copilot-client";
import { ApiError } from "@/lib/api/http";
import type {
  CustomerPreferences as CustomerPreferencesData,
  ThreadMessage,
  WorkbenchCase,
} from "@/lib/gateway/types";
import { useErrorBanner } from "@/components/shell/error-banner";
import { CaseQueue } from "./CaseQueue";
import { CopilotGateway } from "./CopilotGateway";
import { CustomerPreferences } from "./CustomerPreferences";
import { ThreadContext } from "./ThreadContext";
import type { QueueFilter } from "./QueueFilters";

type Thread = { case: WorkbenchCase; messages: ThreadMessage[] };

type LoadOpts = { silent?: boolean };

// ponytail: client poll while Copilot is open; pause when tab hidden (no SSE/WebSocket yet)
const POLL_MS = 4_000;

function isSupervisorOrAdmin(role: WorkbenchRoleId): boolean {
  return role === WORKBENCH_ROLES.supervisor || role === WORKBENCH_ROLES.admin;
}

function defaultFilter(role: WorkbenchRoleId): QueueFilter {
  return {
    statuses: ["open", "in_progress"],
    assignee: isSupervisorOrAdmin(role) ? "all" : "mine_or_unassigned",
  };
}

export function CopilotDashboard({
  accountId,
  role,
}: {
  accountId: string;
  role: WorkbenchRoleId;
}) {
  const { showError } = useErrorBanner();
  const [filter, setFilter] = useState<QueueFilter>(() => defaultFilter(role));
  const [cases, setCases] = useState<WorkbenchCase[]>([]);
  const [loadingCases, setLoadingCases] = useState(true);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [thread, setThread] = useState<Thread | null>(null);
  const [preferences, setPreferences] = useState<CustomerPreferencesData>({});

  const elevated = isSupervisorOrAdmin(role);

  const surface = useCallback(
    (err: unknown, fallback: string) => {
      const message = err instanceof ApiError ? err.message : fallback;
      showError(message, err instanceof ApiError ? `HTTP ${err.status}` : undefined);
    },
    [showError],
  );

  const loadCases = useCallback(async (opts?: LoadOpts) => {
    if (!opts?.silent) setLoadingCases(true);
    try {
      const { cases: next } = await copilot.listCases(filter);
      setCases(next);
    } catch (err) {
      if (!opts?.silent) surface(err, "Failed to load the case queue");
    } finally {
      if (!opts?.silent) setLoadingCases(false);
    }
  }, [filter, surface]);

  const loadThread = useCallback(
    async (caseId: string, opts?: LoadOpts) => {
      try {
        setThread(await copilot.getThread(caseId));
      } catch (err) {
        if (!opts?.silent) surface(err, "Failed to load the case thread");
      }
    },
    [surface],
  );

  const loadPreferences = useCallback(
    async (caseId: string, opts?: LoadOpts) => {
      try {
        const { preferences: next } = await copilot.getPreferences(caseId);
        setPreferences(next);
      } catch (err) {
        if (!opts?.silent) surface(err, "Failed to load preferences");
      }
    },
    [surface],
  );

  useEffect(() => {
    void loadCases();
  }, [loadCases]);

  useEffect(() => {
    if (selectedCaseId === null) {
      setThread(null);
      setPreferences({});
      return;
    }
    void loadThread(selectedCaseId);
    void loadPreferences(selectedCaseId);
  }, [selectedCaseId, loadThread, loadPreferences]);

  const refresh = useCallback(
    async (opts?: LoadOpts) => {
      await loadCases(opts);
      if (selectedCaseId !== null) {
        await loadThread(selectedCaseId, opts);
        await loadPreferences(selectedCaseId, opts);
      }
    },
    [loadCases, loadThread, loadPreferences, selectedCaseId],
  );

  useEffect(() => {
    function poll() {
      if (document.hidden) return;
      void refresh({ silent: true });
    }
    const id = window.setInterval(poll, POLL_MS);
    function onVisibility() {
      if (!document.hidden) void refresh({ silent: true });
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh]);

  async function mutate(action: () => Promise<unknown>, fallback: string) {
    try {
      await action();
      await refresh();
    } catch (err) {
      surface(err, fallback);
    }
  }

  const selectedCase = thread?.case ?? null;

  return (
    <div style={{ display: "flex", gap: "1rem", alignItems: "stretch", minHeight: "70vh" }}>
      <div style={{ flex: "1 1 50%", minWidth: 0, borderRight: "1px solid #e2e2e2" }}>
        <CaseQueue
          cases={cases}
          accountId={accountId}
          selectedCaseId={selectedCaseId}
          onSelect={setSelectedCaseId}
          filter={filter}
          onFilterChange={setFilter}
          canViewAllTeam={elevated}
          loading={loadingCases}
        />
      </div>

      <div style={{ flex: "1 1 50%", minWidth: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        <div
          style={{
            flex: "1 1 55%",
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            borderBottom: "1px solid #e2e2e2",
          }}
        >
          {thread !== null ? (
            <ThreadContext
              case={thread.case}
              messages={thread.messages}
              accountId={accountId}
              role={role}
              onClaim={() => mutate(() => copilot.claimCase(thread.case.caseId), "Failed to claim case")}
              onResolve={() => mutate(() => copilot.resolveCase(thread.case.caseId), "Failed to resolve case")}
              onSetPriority={(urgent) =>
                mutate(() => copilot.setPriority(thread.case.caseId, urgent), "Failed to update priority")
              }
              onSetContactReason={(reason) =>
                mutate(() => copilot.setContactReason(thread.case.caseId, reason), "Failed to update contact reason")
              }
              onAssign={(assignee) =>
                mutate(() => copilot.assignCase(thread.case.caseId, assignee), "Failed to assign case")
              }
            />
          ) : (
            <p style={{ padding: "1rem", color: "#666" }}>
              Select a case from the queue to view its thread.
            </p>
          )}
        </div>

        {thread !== null ? (
          <div style={{ flex: "0 0 auto", borderBottom: "1px solid #e2e2e2" }}>
            <CustomerPreferences
              preferences={preferences}
              onUpsert={(slot, value) =>
                mutate(
                  () => copilot.upsertPreference(thread.case.caseId, slot, value),
                  "Failed to update preference",
                )
              }
              onClear={(slot) =>
                mutate(
                  () => copilot.clearPreference(thread.case.caseId, slot),
                  "Failed to clear preference",
                )
              }
            />
          </div>
        ) : null}

        <div style={{ flex: "1 1 45%", minHeight: 0, overflowY: "auto" }}>
          <CopilotGateway
            case={selectedCase}
            accountId={accountId}
            chat={(message) => copilot.chat(message, selectedCaseId ?? undefined)}
            draft={async (kind: DraftKind) => {
              const id = selectedCaseId;
              if (id === null) return "";
              const { draft } = await copilot.draft(kind, id);
              return copilot.normalizeDraft(draft);
            }}
            onSent={() => {
              void refresh();
            }}
          />
        </div>
      </div>
    </div>
  );
}

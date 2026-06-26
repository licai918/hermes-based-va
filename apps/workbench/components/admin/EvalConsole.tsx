"use client";

// Launch Eval Review master-detail console (ADR-0088): eval runs on the left
// (most recent first), the selected run's report on the right. Sign-off and
// promotion follow the Knowledge Publish Eval Gate (ADR-0040): high-severity
// failures block everything, medium failures need sign-off before a
// policy_publish run can be promoted. Split into a pure view + fetching container.
import { useCallback, useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { useErrorBanner } from "@/components/shell/error-banner";
import { getRun, listRuns, promote, signOff } from "@/lib/api/admin-client";
import { ApiError } from "@/lib/api/http";
import { formatRelativeTime } from "@/lib/format";
import type { EvalRunReport, EvalRunSummary } from "@/lib/gateway/eval-store";

function chipStyle(color: string) {
  return {
    fontSize: "0.6875rem",
    fontWeight: 600,
    color,
    border: `1px solid ${color}`,
    borderRadius: "999px",
    padding: "0.05rem 0.5rem",
    whiteSpace: "nowrap" as const,
  };
}

function PassFail({ passed }: { passed: boolean }) {
  return (
    <span style={chipStyle(passed ? "#15803d" : "#b91c1c")}>
      {passed ? "Pass" : "Fail"}
    </span>
  );
}

function SeverityChips({
  failedHigh,
  failedMedium,
}: {
  failedHigh: number;
  failedMedium: number;
}) {
  return (
    <>
      {failedHigh > 0 ? (
        <span style={chipStyle("#b91c1c")}>High: {failedHigh}</span>
      ) : null}
      {failedMedium > 0 ? (
        <span style={chipStyle("#b45309")}>Medium: {failedMedium}</span>
      ) : null}
    </>
  );
}

export type EvalConsoleViewProps = {
  runs: EvalRunSummary[];
  selectedRun: EvalRunReport | null;
  busy: boolean;
  error: string | null;
  now: number;
  onSelect: (runId: string) => void;
  onSignOff: () => void;
  onPromote: () => void;
};

function canSignOff(run: EvalRunReport, busy: boolean): boolean {
  return (
    !busy &&
    run.signoff_required &&
    run.summary.failed_high === 0 &&
    !run.signed_off
  );
}

function canPromote(run: EvalRunReport, busy: boolean): boolean {
  return (
    !busy &&
    run.suite === "policy_publish" &&
    run.summary.failed_high === 0 &&
    (!run.signoff_required || Boolean(run.signed_off)) &&
    !run.promoted
  );
}

export function EvalConsoleView({
  runs,
  selectedRun,
  busy,
  error,
  now,
  onSelect,
  onSignOff,
  onPromote,
}: EvalConsoleViewProps) {
  return (
    <div style={{ display: "flex", gap: "1.5rem", alignItems: "flex-start" }}>
      <nav aria-label="Eval runs" style={{ width: "20rem", flexShrink: 0 }}>
        {runs.length === 0 ? (
          <EmptyState title="No eval runs yet" description="Runs appear here once the eval runner reports." />
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {runs.map((run) => {
              const active = run.run_id === selectedRun?.run_id;
              return (
                <li key={run.run_id}>
                  <button
                    type="button"
                    onClick={() => onSelect(run.run_id)}
                    aria-current={active}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      padding: "0.5rem 0.625rem",
                      marginBottom: "0.25rem",
                      border: "1px solid #e2e2e2",
                      borderRadius: "0.375rem",
                      background: active ? "#eef2ff" : "#fff",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>{run.run_id}</div>
                    <div style={{ fontSize: "0.8125rem", opacity: 0.7 }}>
                      {run.suite} · {formatRelativeTime(Date.parse(run.timestamp), now)}
                    </div>
                    <div
                      style={{
                        display: "flex",
                        gap: "0.375rem",
                        marginTop: "0.25rem",
                        flexWrap: "wrap",
                      }}
                    >
                      <PassFail passed={run.passed} />
                      <SeverityChips
                        failedHigh={run.failed_high}
                        failedMedium={run.failed_medium}
                      />
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      <section style={{ flex: 1, minWidth: 0 }}>
        {selectedRun ? (
          <>
            <div
              style={{
                display: "flex",
                gap: "0.75rem",
                alignItems: "center",
                flexWrap: "wrap",
                marginBottom: "0.5rem",
              }}
            >
              <h2 style={{ margin: 0, fontSize: "1.125rem" }}>{selectedRun.run_id}</h2>
              <PassFail
                passed={
                  selectedRun.summary.failed_high === 0 &&
                  selectedRun.summary.failed_medium === 0
                }
              />
              <SeverityChips
                failedHigh={selectedRun.summary.failed_high}
                failedMedium={selectedRun.summary.failed_medium}
              />
            </div>

            <dl
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "0.125rem 0.75rem",
                margin: "0 0 0.75rem",
                fontSize: "0.875rem",
              }}
            >
              <dt style={{ opacity: 0.7 }}>Suite</dt>
              <dd style={{ margin: 0 }}>{selectedRun.suite}</dd>
              <dt style={{ opacity: 0.7 }}>Model</dt>
              <dd style={{ margin: 0 }}>{selectedRun.model_slug}</dd>
              <dt style={{ opacity: 0.7 }}>Prompt</dt>
              <dd style={{ margin: 0 }}>{selectedRun.prompt_version}</dd>
              <dt style={{ opacity: 0.7 }}>Knowledge</dt>
              <dd style={{ margin: 0 }}>{selectedRun.knowledge_version}</dd>
              <dt style={{ opacity: 0.7 }}>Result</dt>
              <dd style={{ margin: 0 }}>
                {selectedRun.summary.passed}/{selectedRun.summary.total} passed
              </dd>
              <dt style={{ opacity: 0.7 }}>Status</dt>
              <dd style={{ margin: 0 }}>
                {selectedRun.signed_off ? "Signed off" : "Not signed off"} ·{" "}
                {selectedRun.promoted ? "Promoted" : "Not promoted"}
              </dd>
            </dl>

            <h3 style={{ margin: "0 0 0.25rem", fontSize: "0.9375rem" }}>Scenarios</h3>
            <ul style={{ listStyle: "none", margin: "0 0 0.75rem", padding: 0 }}>
              {selectedRun.scenarios.map((sc) => (
                <li
                  key={sc.scenario_id}
                  style={{
                    padding: "0.375rem 0",
                    borderBottom: "1px solid #f0f0f0",
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{sc.scenario_id}</span>{" "}
                  <PassFail passed={sc.passed} />
                  {sc.failed_assertions.length > 0 ? (
                    <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.25rem" }}>
                      {sc.failed_assertions.map((a) => (
                        <li key={a} style={{ color: "#b91c1c" }}>
                          {a}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>

            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={onSignOff}
                disabled={!canSignOff(selectedRun, busy)}
              >
                Sign off medium
              </button>
              <button
                type="button"
                onClick={onPromote}
                disabled={!canPromote(selectedRun, busy)}
              >
                Promote
              </button>
            </div>

            {error ? (
              <p role="alert" style={{ color: "#8a1c1c", marginBottom: 0 }}>
                {error}
              </p>
            ) : null}
          </>
        ) : (
          <EmptyState
            title="Select an eval run"
            description="Choose a run from the list to review its scenarios and gate status."
          />
        )}
      </section>
    </div>
  );
}

export function EvalConsole() {
  const { showError } = useErrorBanner();
  const [runs, setRuns] = useState<EvalRunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvalRunReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    listRuns()
      .then(setRuns)
      .catch((e) => {
        const msg = e instanceof ApiError ? e.message : "Failed to load eval runs";
        setError(msg);
        showError(msg);
      });
  }, [showError]);

  const handleSelect = useCallback(
    (runId: string) => {
      setError(null);
      getRun(runId)
        .then(setSelectedRun)
        .catch((e) => {
          const msg = e instanceof ApiError ? e.message : "Failed to load run";
          showError(msg);
        });
    },
    [showError],
  );

  async function runAction(action: () => Promise<EvalRunReport>) {
    setBusy(true);
    setError(null);
    try {
      setSelectedRun(await action());
      setRuns(await listRuns());
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Action failed";
      setError(msg);
      showError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <EvalConsoleView
      runs={runs}
      selectedRun={selectedRun}
      busy={busy}
      error={error}
      now={now}
      onSelect={handleSelect}
      onSignOff={() =>
        selectedRun && runAction(() => signOff(selectedRun.run_id))
      }
      onPromote={() =>
        selectedRun && runAction(() => promote(selectedRun.run_id))
      }
    />
  );
}

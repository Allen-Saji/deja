"use client";

import {
  Activity,
  ArrowRight,
  BookOpenCheck,
  BrainCircuit,
  Check,
  CircleDashed,
  Clock3,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { LearningCurve } from "@/components/learning-curve";
import {
  compactIdentifier,
  formatDuration,
  formatPercent,
  formatTimestamp,
  humanize,
} from "@/lib/format";
import { bestReplayImprovement } from "@/lib/snapshot";
import type {
  DashboardSnapshot,
  IncidentRun,
  NoiseLedger,
  Runbook,
} from "@/lib/types";

const WORKFLOW_NODES = ["ingest", "recall", "triage", "act", "writeback"];

function StatusDot({ status }: { status: string }) {
  return <span className={`status-dot status-${status}`} aria-hidden="true" />;
}

function Stat({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail: string;
}) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <div className="stat-value-row">
        <strong>{value}</strong>
        <ArrowRight size={14} aria-hidden="true" />
      </div>
      <small>{detail}</small>
    </div>
  );
}

function RunTimeline({ run }: { run: IncidentRun }) {
  const effectNodes = new Set(run.nodeEffects.map((effect) => effect.node));
  const currentNodeIndex = WORKFLOW_NODES.indexOf(run.currentStep);
  const hasNodeEffects = effectNodes.size > 0;
  return (
    <div className="timeline-block">
      <div className="timeline-head">
        <span>Execution trace</span>
        <span>
          {run.attemptCount || 1} attempt{(run.attemptCount || 1) === 1 ? "" : "s"}
        </span>
      </div>
      <div className="workflow-trace">
        {WORKFLOW_NODES.map((node, index) => {
          const inferredLegacyCompletion =
            !hasNodeEffects && currentNodeIndex >= 0 && index < currentNodeIndex;
          const complete =
            run.status === "completed" || effectNodes.has(node) || inferredLegacyCompletion;
          const failed = run.status === "failed" && run.currentStep === node;
          const active =
            (run.status === "running" || run.status === "queued") && run.currentStep === node;
          return (
            <div
              className="trace-segment"
              key={node}
              style={{ "--trace-index": index } as React.CSSProperties}
            >
              <div
                className={`trace-node ${complete ? "complete" : ""} ${failed ? "failed" : ""} ${active ? "active" : ""}`}
              >
                {complete ? (
                  <Check size={14} aria-hidden="true" />
                ) : (
                  <CircleDashed size={14} aria-hidden="true" />
                )}
                <span>{node}</span>
              </div>
              {index < WORKFLOW_NODES.length - 1 ? <div className="trace-line" /> : null}
            </div>
          );
        })}
      </div>
      {run.attempts.length > 0 ? (
        <div className="attempt-ledger">
          {run.attempts.map((attempt) => (
            <div className="attempt" key={attempt.attemptNumber}>
              <span className="attempt-index">0{attempt.attemptNumber}</span>
              <div>
                <strong>{humanize(attempt.status)}</strong>
                <small>resume: {attempt.resumedFrom}</small>
              </div>
              <time>{formatTimestamp(attempt.startedAt)}</time>
              {attempt.errorType ? <code>{attempt.errorType}</code> : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="legacy-note">Per-attempt audit rows were not available for this run.</p>
      )}
    </div>
  );
}

function RunDetail({ run }: { run: IncidentRun }) {
  const diagnosis =
    run.triage?.diagnosis ??
    (run.status === "failed" && run.diagnosisMs !== null
      ? "Diagnosis completed, but final incident writeback did not persist."
      : "Diagnosis pending.");

  return (
    <article className="run-detail" key={run.runId}>
      <div className="run-detail-head">
        <div>
          <p className="detail-status">
            <StatusDot status={run.status} />
            {humanize(run.status)}
            <span>{run.incidentId}</span>
          </p>
          <h2>{run.service}</h2>
          <p className="detail-signal">{run.alertType}</p>
        </div>
        <div className={`severity-stamp severity-${run.severity}`}>{run.severity}</div>
      </div>
      <p className="alert-message">{run.message}</p>
      <RunTimeline run={run} />
      <div className="incident-story">
        <section className="diagnosis-copy" aria-labelledby="diagnosis-title">
          <span id="diagnosis-title">Diagnosis</span>
          <p>{diagnosis}</p>
          <div className="action-boundary">
            <ShieldCheck size={16} aria-hidden="true" />
            <div>
              <strong>Advisory boundary</strong>
              <p>
                {humanize(run.actionOutcome)}. Deja records evidence and never changes
                infrastructure.
              </p>
            </div>
          </div>
        </section>
        <aside className="memory-trail" aria-label="Memory trail">
          <div className="memory-trail-heading">
            <span>Memory trail</span>
            <BrainCircuit size={16} aria-hidden="true" />
          </div>
          {[
            ["Current alert", run.alertType],
            [
              "Recalled precedent",
              run.precedentIds.length > 0
                ? run.precedentIds.map(compactIdentifier).join(", ")
                : "Novel incident",
            ],
            ["Diagnosis", run.triage ? "Validated" : "Pending"],
            ["Recommendation", run.selectedRunbookName ?? "No runbook match"],
            ["Operator outcome", humanize(run.actionOutcome)],
          ].map(([label, value], index) => (
            <div
              className="memory-step"
              key={label}
              style={{ "--memory-index": index } as React.CSSProperties}
            >
              <i aria-hidden="true" />
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </aside>
      </div>
      <div className="evidence-strip">
        <div>
          <span>Time to diagnose</span>
          <strong>{formatDuration(run.diagnosisMs)}</strong>
        </div>
        <div>
          <span>Precedent evidence</span>
          <strong>
            {run.precedentIds.length > 0
              ? run.precedentIds.map(compactIdentifier).join(", ")
              : "NOVEL"}
          </strong>
        </div>
        <div>
          <span>Runbook</span>
          <strong>{run.selectedRunbookName ?? "No match"}</strong>
        </div>
      </div>
    </article>
  );
}

function IncidentFeed({
  runs,
  selectedRunId,
  onSelect,
}: {
  runs: IncidentRun[];
  selectedRunId: string;
  onSelect: (runId: string) => void;
}) {
  return (
    <section className="panel feed-panel" aria-labelledby="feed-title">
      <div className="panel-heading compact">
        <div>
          <p className="eyebrow">Durable ledger</p>
          <h2 id="feed-title">Recent runs</h2>
        </div>
        <span className="record-count">{runs.length} loaded</span>
      </div>
      <div className="incident-list">
        {runs.map((run, index) => (
          <button
            type="button"
            className={`incident-row ${selectedRunId === run.runId ? "selected" : ""}`}
            key={run.runId}
            onClick={() => onSelect(run.runId)}
            aria-pressed={selectedRunId === run.runId}
            style={{ "--row-index": Math.min(index, 9) } as React.CSSProperties}
          >
            <StatusDot status={run.status} />
            <span className="incident-service">
              <strong>{run.service}</strong>
              <small>{run.alertType}</small>
            </span>
            <span className="incident-memory">
              {run.precedentIds.length > 0 ? (
                <>
                  <BrainCircuit size={14} aria-hidden="true" />
                  {run.precedentIds.length}
                </>
              ) : (
                "new"
              )}
            </span>
            <span className="incident-time">{formatDuration(run.diagnosisMs)}</span>
            <time>{formatTimestamp(run.startedAt)}</time>
            <ArrowRight className="incident-arrow" size={15} aria-hidden="true" />
          </button>
        ))}
      </div>
    </section>
  );
}

function NoiseTable({ ledgers }: { ledgers: NoiseLedger[] }) {
  return (
    <section className="panel noise-panel" aria-labelledby="noise-title">
      <div className="panel-heading compact">
        <div>
          <p className="eyebrow">Procedural memory</p>
          <h2 id="noise-title">Noise ledger</h2>
        </div>
        <span className="panel-index">01</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Signal</th>
              <th>Seen</th>
              <th>Stable</th>
              <th>Notify</th>
            </tr>
          </thead>
          <tbody>
            {ledgers.map((ledger) => (
              <tr key={ledger.fingerprint}>
                <td>
                  <strong>{ledger.service}</strong>
                  <small>{ledger.alertType}</small>
                </td>
                <td>{ledger.occurrenceCount}</td>
                <td>{ledger.stableCount}</td>
                <td>
                  <span className={`decision-chip ${ledger.notificationSuppressed ? "muted" : ""}`}>
                    {ledger.notificationSuppressed ? "suppressed" : "delivered"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RunbookBoard({ runbooks }: { runbooks: Runbook[] }) {
  return (
    <section className="panel runbook-panel" aria-labelledby="runbook-title">
      <div className="panel-heading compact">
        <div>
          <p className="eyebrow">Outcome evidence</p>
          <h2 id="runbook-title">Runbook performance</h2>
        </div>
        <BookOpenCheck size={18} strokeWidth={1.7} aria-hidden="true" />
      </div>
      <div className="runbook-list">
        {runbooks.map((runbook, index) => (
          <div className="runbook-row" key={runbook.runbookId}>
            <span className="rank">0{index + 1}</span>
            <div className="runbook-name">
              <strong>{runbook.name}</strong>
              <small>
                {runbook.service} / {runbook.alertType}
              </small>
            </div>
            <div className="efficacy">
              <span>{formatPercent(runbook.efficacyScore)}</span>
              <div className="efficacy-track">
                <i style={{ width: `${runbook.efficacyScore * 100}%` }} />
              </div>
            </div>
            <span className="sample-count">n={runbook.sampleCount}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function Dashboard({
  initialSnapshot,
}: {
  initialSnapshot: DashboardSnapshot;
}) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [selectedRunId, setSelectedRunId] = useState(initialSnapshot.runs[0]?.runId ?? "");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const selectedRun = useMemo(
    () => snapshot.runs.find((run) => run.runId === selectedRunId) ?? snapshot.runs[0],
    [selectedRunId, snapshot.runs],
  );
  const replayImprovement = useMemo(
    () => bestReplayImprovement(snapshot.learningCurve),
    [snapshot.learningCurve],
  );

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setRefreshError(false);
    try {
      const response = await fetch("/api/snapshot", { cache: "no-store" });
      if (!response.ok) {
        throw new Error("snapshot refresh failed");
      }
      const nextSnapshot = (await response.json()) as DashboardSnapshot;
      setSnapshot(nextSnapshot);
      setSelectedRunId((current) =>
        nextSnapshot.runs.some((run) => run.runId === current)
          ? current
          : (nextSnapshot.runs[0]?.runId ?? ""),
      );
    } catch {
      setRefreshError(true);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void refresh();
      }
    }, 30_000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  return (
    <div className="deja-app">
      <header className="app-bar">
        <div className="app-bar-inner">
          <a className="wordmark" href="#overview" aria-label="Deja overview">
            <span className="wordmark-glyph" aria-hidden="true">
              d
            </span>
            <span>deja</span>
          </a>
          <nav className="primary-nav" aria-label="Primary navigation">
            <a href="#overview">Overview</a>
            <a className="active" href="#runs">
              Runs
            </a>
            <a href="#memory">Memory</a>
            <a href="#runbooks">Runbooks</a>
          </nav>
          <div className="app-actions">
            <div className="live-cluster">
              <span className="live-pulse" />
              <span>Production</span>
              <small>CRDB / Mumbai</small>
            </div>
            <button
              type="button"
              className="refresh-button"
              onClick={refresh}
              disabled={refreshing}
            >
              <RefreshCw size={15} className={refreshing ? "spin" : ""} aria-hidden="true" />
              <span>{refreshing ? "Refreshing" : "Refresh"}</span>
            </button>
          </div>
        </div>
      </header>

      <main className="console-main">
        <section className="console-intro" id="overview">
          <div>
            <p className="section-label">
              <span className="live-pulse" />
              Live operational memory
            </p>
            <h1>Incident memory</h1>
            <p>
              A durable record of what failed, what survived, and what the system learned for the
              next response.
            </p>
          </div>
          <div className="trust-cluster" aria-label="System trust boundary">
            <div>
              <span>AWS Lambda</span>
              <small>Execution</small>
            </div>
            <i aria-hidden="true" />
            <div>
              <span>CockroachDB</span>
              <small>Durable memory</small>
            </div>
            <i aria-hidden="true" />
            <div className={snapshot.mcpReadOnlyVerified ? "verified" : "pending"}>
              <span>MCP</span>
              <small>{snapshot.mcpReadOnlyVerified ? "Read only" : "Auth pending"}</small>
            </div>
          </div>
        </section>

        {refreshError ? (
          <div className="refresh-error" role="status">
            <RotateCcw size={15} aria-hidden="true" />
            Refresh failed. Showing the last verified snapshot.
          </div>
        ) : null}

        <section className="stats-grid" aria-label="Operational summary">
          <Stat
            label="Completed runs"
            value={snapshot.metrics.completedRuns}
            detail={`${snapshot.metrics.totalRuns} total durable runs`}
          />
          <Stat
            label="Memory assisted"
            value={snapshot.metrics.precedentAssistedRuns}
            detail="validated citations"
          />
          <Stat
            label="Retry recoveries"
            value={snapshot.metrics.recoveredRuns}
            detail="resumed from checkpoint"
          />
          <Stat
            label="Best replay"
            value={replayImprovement === null ? "N/A" : `${replayImprovement.toFixed(0)}%`}
            detail="verified faster diagnosis"
          />
        </section>

        <section className="operations-grid" id="runs">
          <IncidentFeed
            runs={snapshot.runs}
            selectedRunId={selectedRun?.runId ?? ""}
            onSelect={setSelectedRunId}
          />
          <section className="panel detail-panel" aria-label="Selected incident detail">
            {selectedRun ? (
              <RunDetail key={selectedRun.runId} run={selectedRun} />
            ) : (
              <p>No incident records found.</p>
            )}
          </section>
        </section>

        <div id="memory">
          <LearningCurve points={snapshot.learningCurve} />
        </div>

        <section className="memory-grid">
          <NoiseTable ledgers={snapshot.noiseLedgers} />
          <div id="runbooks">
            <RunbookBoard runbooks={snapshot.runbooks} />
          </div>
        </section>

        <footer>
          <div>
            <Activity size={16} aria-hidden="true" />
            <span>Snapshot {formatTimestamp(snapshot.generatedAt)} UTC</span>
          </div>
          <p>Advisory only. Recommendations are recorded, never executed.</p>
          <div>
            <Clock3 size={16} aria-hidden="true" />
            <span>Auto-refresh / 30s</span>
          </div>
        </footer>
      </main>
    </div>
  );
}

"use client";

import {
  Activity,
  BookOpenCheck,
  BrainCircuit,
  Check,
  CircleDashed,
  Clock3,
  CloudCog,
  Database,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Siren,
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
      <span>{label}</span>
      <strong>{value}</strong>
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
        <span>EXECUTION TRACE</span>
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
            <div className="trace-segment" key={node}>
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
    <article className="run-detail">
      <div className="run-detail-head">
        <div>
          <p className="eyebrow">SELECTED RECORD / {run.incidentId}</p>
          <h2>{run.service}</h2>
          <p>{run.alertType}</p>
        </div>
        <div className={`severity-stamp severity-${run.severity}`}>{run.severity}</div>
      </div>
      <p className="alert-message">{run.message}</p>
      <RunTimeline run={run} />
      <div className="diagnosis-grid">
        <div>
          <span>DIAGNOSIS</span>
          <p>{diagnosis}</p>
        </div>
        <div>
          <span>ACTION BOUNDARY</span>
          <p>{humanize(run.actionOutcome)}</p>
        </div>
      </div>
      <div className="evidence-strip">
        <div>
          <span>TIME TO DIAGNOSE</span>
          <strong>{formatDuration(run.diagnosisMs)}</strong>
        </div>
        <div>
          <span>PRECEDENT EVIDENCE</span>
          <strong>
            {run.precedentIds.length > 0
              ? run.precedentIds.map(compactIdentifier).join(", ")
              : "NOVEL"}
          </strong>
        </div>
        <div>
          <span>RUNBOOK</span>
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
          <p className="eyebrow">DURABLE LEDGER / LATEST 50</p>
          <h2 id="feed-title">Incident feed</h2>
        </div>
        <span className="record-count">{runs.length} records loaded</span>
      </div>
      <div className="incident-list">
        {runs.map((run) => (
          <button
            type="button"
            className={`incident-row ${selectedRunId === run.runId ? "selected" : ""}`}
            key={run.runId}
            onClick={() => onSelect(run.runId)}
            aria-pressed={selectedRunId === run.runId}
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
          <p className="eyebrow">PROCEDURAL MEMORY / DUPLICATES</p>
          <h2 id="noise-title">Noise ledger</h2>
        </div>
        <Siren size={22} strokeWidth={1.6} aria-hidden="true" />
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
          <p className="eyebrow">PROCEDURAL MEMORY / OUTCOMES</p>
          <h2 id="runbook-title">Runbook leaderboard</h2>
        </div>
        <BookOpenCheck size={22} strokeWidth={1.6} aria-hidden="true" />
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
    <main>
      <header className="masthead">
        <div className="brand-lockup">
          <div className="brand-mark">D</div>
          <div>
            <p>DEJA / MEMORY OPERATIONS</p>
            <span>INCIDENT RESPONSE THAT REMEMBERS</span>
          </div>
        </div>
        <div className="live-cluster">
          <span className="live-pulse" />
          <div>
            <strong>LIVE DATA</strong>
            <small>CRDB CLOUD / MUMBAI</small>
          </div>
        </div>
        <button type="button" className="refresh-button" onClick={refresh} disabled={refreshing}>
          <RefreshCw size={15} className={refreshing ? "spin" : ""} aria-hidden="true" />
          {refreshing ? "Refreshing" : "Refresh"}
        </button>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">CONTROL SURFACE / P4</p>
          <h1>
            Every incident leaves
            <br />
            <em>a usable memory.</em>
          </h1>
        </div>
        <div className="hero-copy">
          <p>
            Follow each alert from ingestion to postmortem. See which checkpoint survived, which
            precedent shaped the diagnosis, and which operator outcome changed the next response.
          </p>
          <div className="system-rail" aria-label="System architecture status">
            <span>
              <CloudCog size={17} aria-hidden="true" /> AWS Lambda
            </span>
            <i />
            <span>
              <Database size={17} aria-hidden="true" /> CockroachDB
            </span>
            <i />
            <span className={snapshot.mcpReadOnlyVerified ? "verified" : "pending"}>
              <ShieldCheck size={17} aria-hidden="true" />
              MCP {snapshot.mcpReadOnlyVerified ? "read only" : "auth pending"}
            </span>
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
          label="COMPLETED"
          value={snapshot.metrics.completedRuns}
          detail={`of ${snapshot.metrics.totalRuns} durable runs`}
        />
        <Stat
          label="MEMORY ASSISTS"
          value={snapshot.metrics.precedentAssistedRuns}
          detail="validated precedent citations"
        />
        <Stat
          label="NOISE MUTED"
          value={snapshot.metrics.suppressedNotifications}
          detail="processing still completed"
        />
        <Stat
          label="RETRY RECOVERIES"
          value={snapshot.metrics.recoveredRuns}
          detail="checkpoint-resumed runs"
        />
      </section>

      <section className="operations-grid">
        <IncidentFeed
          runs={snapshot.runs}
          selectedRunId={selectedRun?.runId ?? ""}
          onSelect={setSelectedRunId}
        />
        <section className="panel detail-panel" aria-label="Selected incident detail">
          {selectedRun ? <RunDetail run={selectedRun} /> : <p>No incident records found.</p>}
        </section>
      </section>

      <LearningCurve points={snapshot.learningCurve} />

      <section className="memory-grid">
        <NoiseTable ledgers={snapshot.noiseLedgers} />
        <RunbookBoard runbooks={snapshot.runbooks} />
      </section>

      <footer>
        <div>
          <Activity size={16} aria-hidden="true" />
          <span>Snapshot {formatTimestamp(snapshot.generatedAt)} UTC</span>
        </div>
        <p>
          Advisory only. Deja records recommendations and operator evidence but never changes
          infrastructure.
        </p>
        <div>
          <Clock3 size={16} aria-hidden="true" />
          <span>Auto-refresh / 30s</span>
        </div>
      </footer>
    </main>
  );
}

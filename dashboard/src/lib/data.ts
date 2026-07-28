import "server-only";

import { attachDatabasePool } from "@vercel/functions";
import { Pool } from "pg";

import {
  buildLearningCurve,
  metricsFromRow,
  sanitizePublicText,
} from "@/lib/snapshot";
import type {
  DashboardSnapshot,
  IncidentRun,
  NoiseLedger,
  RunAttempt,
  Runbook,
} from "@/lib/types";

type DatabaseRow = Record<string, unknown>;

declare global {
  var dejaDashboardPool: Pool | undefined;
}

function databaseUrl(): string {
  const value = process.env.DEJA_DATABASE_URL?.trim();
  if (!value) {
    throw new Error("DEJA_DATABASE_URL is not configured");
  }
  return value;
}

function pool(): Pool {
  if (!globalThis.dejaDashboardPool) {
    globalThis.dejaDashboardPool = new Pool({
      connectionString: databaseUrl(),
      max: 3,
      connectionTimeoutMillis: 8_000,
      idleTimeoutMillis: 20_000,
      query_timeout: 10_000,
      statement_timeout: 8_000,
      application_name: "deja-dashboard",
      ssl: {
        rejectUnauthorized: true,
      },
    });
    attachDatabasePool(globalThis.dejaDashboardPool);
  }
  return globalThis.dejaDashboardPool;
}

function asString(value: unknown): string {
  return String(value ?? "");
}

function asOptionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : String(value);
}

function asNumber(value: unknown): number {
  return Number(value ?? 0);
}

function asBoolean(value: unknown): boolean {
  return value === true || value === "true";
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function mapAttempt(row: DatabaseRow): RunAttempt {
  return {
    attemptNumber: asNumber(row.attempt_number),
    resumedFrom: asString(row.resumed_from),
    status: asString(row.status),
    startedAt: asString(row.started_at),
    finishedAt: asOptionalString(row.finished_at),
    errorType: asOptionalString(row.error_type),
  };
}

function mapRun(row: DatabaseRow): IncidentRun {
  const rawTriage =
    row.triage && typeof row.triage === "object"
      ? (row.triage as NonNullable<IncidentRun["triage"]>)
      : null;
  const triage = rawTriage
    ? {
        ...rawTriage,
        diagnosis: sanitizePublicText(rawTriage.diagnosis),
        recommended_action: sanitizePublicText(rawTriage.recommended_action),
        rationale: sanitizePublicText(rawTriage.rationale),
        postmortem_summary: sanitizePublicText(rawTriage.postmortem_summary),
      }
    : null;
  return {
    runId: asString(row.run_id),
    incidentId: asString(row.incident_id),
    fingerprint: asString(row.fingerprint),
    service: sanitizePublicText(asString(row.service)),
    alertType: sanitizePublicText(asString(row.alert_type)),
    severity: asString(row.severity) as IncidentRun["severity"],
    message: sanitizePublicText(asString(row.message)),
    status: asString(row.status),
    currentStep: asString(row.current_step),
    attemptCount: asNumber(row.attempt_count),
    lastResumeFrom: asOptionalString(row.last_resume_from),
    triage,
    actionOutcome:
      row.action_outcome === null || row.action_outcome === undefined
        ? null
        : sanitizePublicText(asString(row.action_outcome)),
    postmortem:
      row.postmortem === null || row.postmortem === undefined
        ? null
        : sanitizePublicText(asString(row.postmortem)),
    diagnosisMs:
      row.diagnosis_ms === null || row.diagnosis_ms === undefined
        ? null
        : asNumber(row.diagnosis_ms),
    precedentIds: asStringArray(row.precedent_ids),
    notificationSuppressed: asBoolean(row.notification_suppressed),
    selectedRunbookId: asOptionalString(row.selected_runbook_id),
    selectedRunbookName:
      row.selected_runbook_name === null || row.selected_runbook_name === undefined
        ? null
        : sanitizePublicText(asString(row.selected_runbook_name)),
    startedAt: asString(row.started_at),
    completedAt: asOptionalString(row.completed_at),
    attempts: [],
    nodeEffects: [],
  };
}

export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  const client = pool();
  const [metricsResult, runsResult, attemptsResult, effectsResult, noiseResult, runbooksResult] =
    await Promise.all([
      client.query(`
        SELECT
          count(*)::INT8 AS total_runs,
          count(*) FILTER (WHERE status = 'completed')::INT8 AS completed_runs,
          count(*) FILTER (
            WHERE jsonb_array_length(precedent_ids) > 0
          )::INT8 AS precedent_assisted_runs,
          (
            SELECT count(*)::INT8
            FROM deja_alert_noise_observations
            WHERE notification_suppressed = true
          ) AS suppressed_notifications,
          count(*) FILTER (WHERE attempt_count > 1)::INT8 AS recovered_runs
        FROM deja_runs
      `),
      client.query(`
        SELECT
          r.run_id,
          i.incident_id,
          i.fingerprint,
          i.service,
          i.alert_type,
          i.severity,
          i.message,
          r.status,
          r.current_step,
          r.attempt_count,
          r.last_resume_from,
          i.triage,
          i.action_outcome,
          p.summary AS postmortem,
          r.diagnosis_ms,
          r.precedent_ids,
          coalesce(noise.notification_suppressed, false)
            AS notification_suppressed,
          execution.runbook_id AS selected_runbook_id,
          runbook.name AS selected_runbook_name,
          r.started_at::STRING AS started_at,
          r.completed_at::STRING AS completed_at
        FROM deja_runs AS r
        JOIN deja_incidents AS i ON i.incident_id = r.incident_id
        LEFT JOIN deja_postmortems AS p ON p.run_id = r.run_id
        LEFT JOIN deja_alert_noise_observations AS noise ON noise.run_id = r.run_id
        LEFT JOIN deja_runbook_executions AS execution ON execution.run_id = r.run_id
        LEFT JOIN deja_runbooks AS runbook ON runbook.runbook_id = execution.runbook_id
        ORDER BY r.started_at DESC
        LIMIT 50
      `),
      client.query(`
        WITH recent_runs AS (
          SELECT run_id
          FROM deja_runs
          ORDER BY started_at DESC
          LIMIT 50
        )
        SELECT
          attempt.run_id,
          attempt_number,
          resumed_from,
          status,
          started_at::STRING AS started_at,
          finished_at::STRING AS finished_at,
          error_type
        FROM deja_run_attempts AS attempt
        JOIN recent_runs USING (run_id)
        ORDER BY attempt.run_id, attempt_number
      `),
      client.query(`
        WITH recent_runs AS (
          SELECT run_id
          FROM deja_runs
          ORDER BY started_at DESC
          LIMIT 50
        )
        SELECT effect.run_id, node_name, created_at::STRING AS created_at
        FROM deja_node_effects AS effect
        JOIN recent_runs USING (run_id)
        ORDER BY effect.run_id, created_at
      `),
      client.query(`
        SELECT
          ledger.fingerprint,
          coalesce(latest.service, 'unknown') AS service,
          coalesce(latest.alert_type, 'unknown') AS alert_type,
          ledger.occurrence_count,
          ledger.stable_count,
          ledger.notification_suppressed,
          ledger.updated_at::STRING AS updated_at
        FROM deja_alert_noise AS ledger
        LEFT JOIN LATERAL (
          SELECT service, alert_type
          FROM deja_incidents
          WHERE fingerprint = ledger.fingerprint
          ORDER BY created_at DESC
          LIMIT 1
        ) AS latest ON true
        ORDER BY ledger.updated_at DESC
        LIMIT 12
      `),
      client.query(`
        SELECT
          rb.runbook_id,
          rb.name,
          rb.service,
          rb.alert_type,
          rb.recommended_action,
          count(*) FILTER (WHERE execution.succeeded = true)::INT8 AS success_count,
          count(*) FILTER (WHERE execution.succeeded = false)::INT8 AS failure_count,
          count(execution.succeeded)::INT8 AS sample_count,
          (
            (count(*) FILTER (WHERE execution.succeeded = true)) + 1.0
          ) / (count(execution.succeeded) + 2.0) AS efficacy_score
        FROM deja_runbooks AS rb
        LEFT JOIN deja_runbook_executions AS execution
          ON execution.runbook_id = rb.runbook_id
        WHERE rb.enabled = true
        GROUP BY rb.runbook_id, rb.name, rb.service, rb.alert_type,
                 rb.recommended_action
        ORDER BY efficacy_score DESC, sample_count DESC, rb.runbook_id
      `),
    ]);

  const runs = runsResult.rows.map(mapRun);
  const runsById = new Map(runs.map((run) => [run.runId, run]));
  for (const row of attemptsResult.rows) {
    runsById.get(asString(row.run_id))?.attempts.push(mapAttempt(row));
  }
  for (const row of effectsResult.rows) {
    runsById.get(asString(row.run_id))?.nodeEffects.push({
      node: asString(row.node_name),
      createdAt: asString(row.created_at),
    });
  }

  const noiseLedgers: NoiseLedger[] = noiseResult.rows.map((row) => ({
    fingerprint: asString(row.fingerprint),
    service: sanitizePublicText(asString(row.service)),
    alertType: sanitizePublicText(asString(row.alert_type)),
    occurrenceCount: asNumber(row.occurrence_count),
    stableCount: asNumber(row.stable_count),
    notificationSuppressed: asBoolean(row.notification_suppressed),
    updatedAt: asString(row.updated_at),
  }));
  const runbooks: Runbook[] = runbooksResult.rows.map((row) => ({
    runbookId: asString(row.runbook_id),
    name: sanitizePublicText(asString(row.name)),
    service: sanitizePublicText(asString(row.service)),
    alertType: sanitizePublicText(asString(row.alert_type)),
    recommendedAction: sanitizePublicText(asString(row.recommended_action)),
    successCount: asNumber(row.success_count),
    failureCount: asNumber(row.failure_count),
    sampleCount: asNumber(row.sample_count),
    efficacyScore: asNumber(row.efficacy_score),
  }));

  return {
    generatedAt: new Date().toISOString(),
    metrics: metricsFromRow(metricsResult.rows[0] ?? {}),
    runs,
    learningCurve: buildLearningCurve(runs),
    noiseLedgers,
    runbooks,
    mcpReadOnlyVerified:
      process.env.DEJA_MCP_READONLY_VERIFIED?.trim().toLowerCase() === "true",
  };
}

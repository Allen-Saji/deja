import { describe, expect, it } from "vitest";

import { bestReplayImprovement, buildLearningCurve, metricsFromRow } from "@/lib/snapshot";
import type { IncidentRun } from "@/lib/types";

function run(overrides: Partial<IncidentRun>): IncidentRun {
  return {
    runId: "RUN-ONE",
    incidentId: "INC-ONE",
    fingerprint: "a".repeat(64),
    service: "payments-api",
    alertType: "http-500-spike",
    severity: "critical",
    message: "error rate rose",
    status: "completed",
    currentStep: "writeback",
    attemptCount: 1,
    lastResumeFrom: "ingest",
    triage: null,
    actionOutcome: null,
    postmortem: null,
    diagnosisMs: 4_000,
    precedentIds: [],
    notificationSuppressed: false,
    selectedRunbookId: null,
    selectedRunbookName: null,
    startedAt: "2026-07-22T10:00:00Z",
    completedAt: "2026-07-22T10:00:04Z",
    attempts: [],
    nodeEffects: [],
    ...overrides,
  };
}

describe("dashboard snapshot transforms", () => {
  it("keeps measured cold and assisted runs while excluding chaos duration", () => {
    const points = buildLearningCurve([
      run({ runId: "RUN-COLD" }),
      run({
        runId: "RUN-ASSISTED",
        diagnosisMs: 1_500,
        precedentIds: ["INC-PRIOR"],
        startedAt: "2026-07-22T10:01:00Z",
      }),
      run({
        runId: "RUN-TIMEOUT",
        service: "deja-timeout-abc",
        diagnosisMs: 152_000,
      }),
      run({ runId: "RUN-FAST-HARNESS", diagnosisMs: 1 }),
    ]);

    expect(points.map((point) => point.runId)).toEqual(["RUN-COLD", "RUN-ASSISTED"]);
    expect(bestReplayImprovement(points)).toBeCloseTo(62.5);
  });

  it("normalizes CockroachDB count values", () => {
    expect(
      metricsFromRow({
        total_runs: "36",
        completed_runs: "33",
        precedent_assisted_runs: "4",
        suppressed_notifications: "5",
        recovered_runs: "2",
      }),
    ).toEqual({
      totalRuns: 36,
      completedRuns: 33,
      precedentAssistedRuns: 4,
      suppressedNotifications: 5,
      recoveredRuns: 2,
    });
  });
});

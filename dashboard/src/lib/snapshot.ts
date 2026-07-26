import type {
  DashboardMetrics,
  IncidentRun,
  LearningPoint,
} from "@/lib/types";

export function buildLearningCurve(runs: IncidentRun[]): LearningPoint[] {
  return runs
    .filter(
      (run) =>
        run.status === "completed" &&
        run.diagnosisMs !== null &&
        run.diagnosisMs >= 1_000 &&
        !run.service.startsWith("deja-timeout-"),
    )
    .map((run) => ({
      runId: run.runId,
      service: run.service,
      diagnosisMs: run.diagnosisMs as number,
      precedentCount: run.precedentIds.length,
      startedAt: run.startedAt,
    }))
    .sort(
      (left, right) =>
        new Date(left.startedAt).getTime() - new Date(right.startedAt).getTime(),
    );
}

export function bestReplayImprovement(points: LearningPoint[]): number | null {
  const byService = new Map<string, LearningPoint[]>();
  for (const point of points) {
    const existing = byService.get(point.service) ?? [];
    existing.push(point);
    byService.set(point.service, existing);
  }

  let best: number | null = null;
  for (const servicePoints of byService.values()) {
    const cold = servicePoints.find((point) => point.precedentCount === 0);
    const assisted = servicePoints.find(
      (point) =>
        point.precedentCount > 0 &&
        cold !== undefined &&
        new Date(point.startedAt).getTime() > new Date(cold.startedAt).getTime(),
    );
    if (!cold || !assisted || assisted.diagnosisMs >= cold.diagnosisMs) {
      continue;
    }
    const improvement =
      ((cold.diagnosisMs - assisted.diagnosisMs) / cold.diagnosisMs) * 100;
    best = best === null ? improvement : Math.max(best, improvement);
  }
  return best;
}

export function metricsFromRow(row: Record<string, unknown>): DashboardMetrics {
  return {
    totalRuns: Number(row.total_runs ?? 0),
    completedRuns: Number(row.completed_runs ?? 0),
    precedentAssistedRuns: Number(row.precedent_assisted_runs ?? 0),
    suppressedNotifications: Number(row.suppressed_notifications ?? 0),
    recoveredRuns: Number(row.recovered_runs ?? 0),
  };
}

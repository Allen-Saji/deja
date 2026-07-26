export type Severity = "info" | "warning" | "critical";

export type Triage = {
  diagnosis: string;
  confidence: number;
  severity: Severity;
  recommended_action: string;
  rationale: string;
  escalate: boolean;
  postmortem_summary: string;
  cited_incident_ids: string[];
};

export type RunAttempt = {
  attemptNumber: number;
  resumedFrom: string;
  status: string;
  startedAt: string;
  finishedAt: string | null;
  errorType: string | null;
};

export type NodeEffect = {
  node: string;
  createdAt: string;
};

export type IncidentRun = {
  runId: string;
  incidentId: string;
  fingerprint: string;
  service: string;
  alertType: string;
  severity: Severity;
  message: string;
  status: string;
  currentStep: string;
  attemptCount: number;
  lastResumeFrom: string | null;
  triage: Triage | null;
  actionOutcome: string | null;
  postmortem: string | null;
  diagnosisMs: number | null;
  precedentIds: string[];
  notificationSuppressed: boolean;
  selectedRunbookId: string | null;
  selectedRunbookName: string | null;
  startedAt: string;
  completedAt: string | null;
  attempts: RunAttempt[];
  nodeEffects: NodeEffect[];
};

export type NoiseLedger = {
  fingerprint: string;
  service: string;
  alertType: string;
  occurrenceCount: number;
  stableCount: number;
  notificationSuppressed: boolean;
  updatedAt: string;
};

export type Runbook = {
  runbookId: string;
  name: string;
  service: string;
  alertType: string;
  recommendedAction: string;
  successCount: number;
  failureCount: number;
  sampleCount: number;
  efficacyScore: number;
};

export type LearningPoint = {
  runId: string;
  service: string;
  diagnosisMs: number;
  precedentCount: number;
  startedAt: string;
};

export type DashboardMetrics = {
  totalRuns: number;
  completedRuns: number;
  precedentAssistedRuns: number;
  suppressedNotifications: number;
  recoveredRuns: number;
};

export type DashboardSnapshot = {
  generatedAt: string;
  metrics: DashboardMetrics;
  runs: IncidentRun[];
  learningCurve: LearningPoint[];
  noiseLedgers: NoiseLedger[];
  runbooks: Runbook[];
  mcpReadOnlyVerified: boolean;
};

# Deja video script

Target duration: 2:45. Hard limit: less than 3:00.

## 0:00-0:18 - Hook

Visual: public dashboard, metric cards, recent runs.

Narration:

> Incident agents usually forget at the worst possible time. A worker times out, a retry starts
> over, and the next incident ignores what the last one taught us. Deja is incident response
> memory that survives failures and improves the next diagnosis.

## 0:18-0:42 - What Deja remembers

Visual: scroll from Runs to Memory and Runbooks.

Narration:

> Deja stores three kinds of memory in CockroachDB. Working memory checkpoints every graph node.
> Episodic memory retrieves completed incidents through C-SPANN. Procedural memory learns safe
> duplicate suppression and ranks runbooks from operator outcomes.

## 0:42-1:12 - Evidence-assisted diagnosis

Visual: select `RUN-DED9BC1C7367`; show citations, trace, and diagnosis time.

Narration:

> This production run completed in 5.602 seconds and cited two prior incidents. A comparable cold
> run took 40.940 seconds, an 86.3 percent improvement. Vector similarity is not enough by itself:
> Deja filters by service and alert type, requires completed relational records, and rejects any
> model citation outside the retrieved set.

On-screen labels:

- Cold: 40.940 s
- Memory-assisted: 5.602 s
- Measured improvement: 86.3%

## 1:12-1:38 - Live workflow

Visual: terminal running the signed simulator, then dashboard Refresh and newest run.

Narration:

> An IAM-signed alert reaches FastAPI on AWS Lambda. Deja reserves a durable run, queues an
> asynchronous invocation, and executes ingest, recall, triage, act, and writeback. The action is
> advisory. Deja never changes infrastructure.

## 1:38-2:05 - Failure recovery

Visual: select `RUN-65FE655CA00C`; zoom attempt ledger and execution trace.

Narration:

> Here the first Lambda timed out before triage. Its lease expired. Attempt two resumed at triage
> and completed. CockroachDB checkpoints preserve graph state, and first-write-wins node effects
> prevent repeated writes. A separate three-node acceptance also completed after one CockroachDB
> node was removed.

## 2:05-2:31 - Architecture and tool use

Visual: `docs/architecture/deja-architecture.png`.

Narration:

> AWS Lambda provides serverless execution. CockroachDB stores transactional state and the
> distributed vector index in one system. CockroachDB Cloud Managed MCP provides cluster-scoped,
> read-only inspection. The public Next.js dashboard uses a separate principal with select access
> to nine exact tables and no write path.

## 2:31-2:45 - Close

Visual: dashboard hero and repository URL.

Narration:

> Deja turns incident history into durable, inspectable operational memory while keeping the human
> in control. The live app and MIT-licensed source are public now.

## Related

- [Demo recording runbook](demo-runbook.md)
- [Judging map](judging-map.md)
- [Final submission checklist](final-checklist.md)

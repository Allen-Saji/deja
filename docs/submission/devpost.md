# Deja Devpost draft

Official challenge: https://cockroachdb-ai.devpost.com/

## Project name

Deja

## Tagline

Incident response memory that survives failures and improves the next diagnosis.

## One-line summary

Deja is an incident response agent on AWS Lambda that stores execution state, prior incidents,
postmortems, vectors, alert-noise evidence, and runbook outcomes in CockroachDB.

## Inspiration

Incident response agents usually forget the exact moment when memory matters most. A worker times
out, a retry starts from zero, an old postmortem remains disconnected from the current alert, and
duplicate warning noise keeps reaching operators.

Deja treats memory as part of execution. It remembers what each workflow node completed, which
prior incidents are relevant, which alerts became stable duplicates, and which runbooks worked.

## What it does

Deja accepts an IAM-authenticated alert and returns a durable run ID immediately. An asynchronous
Lambda invocation executes five LangGraph nodes:

1. `ingest` persists the alert and run.
2. `recall` retrieves similar completed incidents.
3. `triage` creates a structured diagnosis and cites stored evidence.
4. `act` recommends a runbook or suppresses only a learned duplicate notification.
5. `writeback` records the postmortem and new memory.

Every node is checkpointed in CockroachDB. If Lambda times out, a later invocation claims the
expired lease and resumes from the first unfinished node. Node effects are first-write-wins, so a
retry does not repeat completed writes.

The public dashboard shows durable runs, retry attempts, graph-node effects, memory-assisted
diagnoses, learned noise patterns, runbook efficacy, and measured diagnosis time. The agent is
advisory only. It never changes production infrastructure.

## How it was built

### CockroachDB Distributed Vector Indexing

VoyageAI generates 1,024-dimensional postmortem embeddings. Deja stores them beside structured
incident metadata and applies a CockroachDB C-SPANN index. Recall is restricted to the same
service and alert type, returns at most three candidates, and rejects matches beyond a cosine
distance of 0.35.

The relational incident row remains the authority. A vector match can become model evidence only
when the corresponding incident is complete. The triage result is schema-validated, and cited IDs
must be a subset of the retrieved incidents.

### CockroachDB Cloud Managed MCP Server

Managed MCP provides a separate read-only inspection path for live operational evidence. The
connection is pinned to one cluster with `mcp-cluster-id`, uses the `mcp:read` OAuth scope, and was
verified with the server's read-only `select_query` tool. No MCP mutation tool is part of Deja.

### AWS Lambda

The FastAPI application runs as a Lambda container image behind an AWS IAM-authenticated Function
URL. The HTTP invocation reserves a run and queues an asynchronous self-invocation. Lambda retries,
CockroachDB leases, LangGraph checkpoints, and an attempt ledger provide durable recovery.
Structured events are available in CloudWatch Logs, and images are stored in Amazon ECR.

### Read-only dashboard

The Next.js dashboard runs on Vercel in Mumbai near the CockroachDB cluster. Its database principal
has `CONNECT`, schema `USAGE`, and `SELECT` on nine exact tables. It has no role membership, schema
creation privilege, or mutation endpoint. The browser receives a sanitized snapshot and never
receives database or model-provider credentials.

## Verified results

- 41 durable production runs, including 38 completed runs.
- 7 completed runs used cited incident memory.
- 3 runs recovered through a later attempt.
- Best measured replay improved diagnosis time by 86.3 percent, from 40.940 seconds in
  `RUN-376DC3E77F40` to 5.602 seconds in `RUN-DED9BC1C7367`.
- Controlled timeout run `RUN-65FE655CA00C` recorded an expired first lease, resumed from
  `triage`, and completed on attempt two.
- A local three-node CockroachDB acceptance removed one node before triage and
  `RUN-158320F0EDDE` completed through the surviving quorum.
- Managed MCP read-only access and dashboard least privilege were verified against the live
  cluster.

These values are evidence from the current deployment, not benchmark guarantees. Model-provider
latency and incident complexity vary.

## Challenges

### Making Lambda retries safe

Lambda may deliver work more than once, and a timed-out process cannot clean up its own state.
Deja combines expiring database leases with a durable attempt ledger and per-node first-write-wins
effects. A replacement invocation can take over without allowing a stale worker to continue.

### Keeping semantic memory trustworthy

Vector similarity alone is not enough for an incident diagnosis. Deja filters candidates by
service and alert type, checks distance, requires a completed relational incident, and validates
every model citation against the retrieved set.

### Separating inspection from control

The dashboard and Managed MCP need useful production evidence without gaining mutation authority.
Deja uses separate read-only boundaries and keeps remediation advisory.

## Accomplishments

- Demonstrated checkpoint recovery after a real Lambda timeout.
- Demonstrated continued execution after a CockroachDB node loss.
- Kept vectors and transactional incident state in one database.
- Made every model citation traceable to a stored incident.
- Added learned alert suppression with conservative safety gates.
- Added efficacy-scored runbooks based on recorded operator outcomes.
- Published a public, mobile-responsive operations dashboard and an MIT-licensed repository.

## What was learned

Agent memory is not one storage feature. Working memory needs checkpoints and ownership. Episodic
memory needs retrieval plus citation controls. Procedural memory needs evidence thresholds and
feedback. Treating all three as database state made recovery, inspection, and testing much more
direct.

## What's next

- Add a small operator feedback UI for runbook outcomes.
- Add service-specific evaluation datasets for retrieval quality.
- Add multi-region deployment tests around CockroachDB locality.
- Add configurable human approval integrations while keeping execution advisory by default.

## Links

- Live app: https://deja-khaki.vercel.app
- Source: https://github.com/Allen-Saji/deja
- Architecture:
  https://github.com/Allen-Saji/deja/blob/main/docs/architecture/deja-architecture.png
- Read-only evidence:
  https://github.com/Allen-Saji/deja/blob/main/docs/observability/read-only-access.md

## Submission requirement mapping

| Requirement | Deja evidence |
| --- | --- |
| Public open source repository | Public GitHub repository with an MIT license |
| Functional demo URL | Public Vercel dashboard backed by live CockroachDB data |
| CockroachDB tool 1 | Distributed Vector Indexing through C-SPANN |
| CockroachDB tool 2 | Cloud Managed MCP Server with read-only cluster-scoped access |
| AWS service | AWS Lambda for HTTP and asynchronous agent execution |
| Video under three minutes | [Script and shot list](video-script.md) |

## Sources

- Challenge requirements and judging criteria: https://cockroachdb-ai.devpost.com/
- Official rules: https://cockroachdb-ai.devpost.com/rules
- Managed MCP connection controls:
  https://www.cockroachlabs.com/docs/cockroachcloud/connect-to-the-cockroachdb-cloud-mcp-server

## Related

- [Judging map](judging-map.md)
- [Demo recording runbook](demo-runbook.md)
- [Final submission checklist](final-checklist.md)

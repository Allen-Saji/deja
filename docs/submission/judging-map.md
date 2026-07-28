# Deja judging map

Use this reference while editing the Devpost entry and recording the demo. Each claim points to
public or reproducible evidence.

## Agentic Memory Design

Judge question: Does CockroachDB provide meaningful production memory?

| Memory type | Implementation | Evidence |
| --- | --- | --- |
| Working | LangGraph checkpoints, run leases, attempt ledger, node effects | `src/deja/workflow.py`, `src/deja/repository.py`, `RUN-65FE655CA00C` |
| Episodic | Completed incident embeddings and C-SPANN recall | `src/deja/memory.py`, `RUN-DED9BC1C7367` |
| Procedural | Alert-noise ledger and runbook outcome scores | `src/deja/repository.py`, dashboard Memory and Runbooks sections |

Talk track: CockroachDB is not a passive log. It decides where execution resumes, which evidence
the model may cite, when a duplicate notification becomes suppressible, and which runbook ranks
highest.

## Technical Implementation

Judge question: Are the CockroachDB and AWS integrations correct and safe?

| Integration | Proof |
| --- | --- |
| C-SPANN | 1,024-dimensional vectors, named index, typed metadata filters, distance threshold |
| Managed MCP | Cluster-scoped `mcp:read`, read-only query tool, no mutation call |
| Lambda | IAM Function URL, asynchronous self-invocation, 90-second timeout, expiring execution lease |
| Validation | Pydantic models, closed alert schema, bounded labels, validated citation subset |
| Idempotency | Stable run ID, first-write-wins node effects, stale-worker lease rejection |

Talk track: Show the architecture diagram, then open the timeout run. Attempt one expires; attempt
two starts at `triage`; ingest and recall are not applied again.

## Real-World Impact

Judge question: Does this improve a real operator workflow?

Evidence:

- A current alert can cite prior completed incidents instead of starting from zero.
- The best measured replay reduced diagnosis time from 40.940 seconds to 5.602 seconds.
- Stable duplicate warnings can stop paging operators after three safe observations.
- Operators retain control because Deja recommends actions but does not execute them.

Talk track: The value is less repeated diagnosis, less duplicate noise, and a durable record of why
the agent made each recommendation.

## Production Readiness

Judge question: What happens when dependencies and workers fail?

| Concern | Control | Verification |
| --- | --- | --- |
| Lambda timeout | Checkpoint resume and lease takeover | `RUN-65FE655CA00C` |
| Duplicate delivery | Run claim plus first-write-wins effects | Unit tests and attempt ledger |
| Database node loss | Distributed quorum | `RUN-158320F0EDDE` |
| Prompt injection | Alert and precedent text marked as untrusted evidence | `src/deja/triage.py` |
| False citation | Citation subset validation | Triage and workflow tests |
| Read-only inspection | Dedicated least-privilege principal | `docs/observability/read-only-access.md` |
| Secret exposure | Server-only database query and sanitized snapshot | Public QA report |
| Supply chain | Locked Python and npm dependencies, immutable CI action commits | Lock files and CI |

Be direct about the remaining base-image scan concern: Amazon ECR currently reports two High
Amazon Linux package findings with no fixed package version. Application dependency audits are
clean. Rebuild when Amazon publishes fixed base packages.

## Creativity and Originality

Judge question: What is different from a standard retrieval demo?

Talk track:

- Deja combines working, episodic, and procedural memory in one incident workflow.
- Recovery state and semantic context share one consistent database.
- The model cannot cite arbitrary history; citations are tied to retrieved completed incidents.
- Alert suppression is learned, conservative, and never applies to critical or escalated alerts.
- Runbook ranking changes only from recorded operator outcomes.

## Tool requirement proof

### CockroachDB Distributed Vector Indexing

- Code: `src/deja/memory.py`
- Table: `deja_precedent_vectors`
- Index: `deja_precedent_cspann_idx`
- Demo: Memory section and a precedent-assisted run

### CockroachDB Cloud Managed MCP Server

- Evidence: `docs/observability/read-only-access.md`
- Access: one cluster, `mcp:read`
- Tool used: read-only `select_query`
- Demo: MCP read-only badge and evidence note

### AWS Lambda

- Code: `src/deja/app.py`, `src/deja/execution.py`
- Deployment: `scripts/deploy.sh`
- Demo: timeout run with two attempts and checkpoint resume

## Related

- [Devpost draft](devpost.md)
- [Video script](video-script.md)
- [Demo recording runbook](demo-runbook.md)

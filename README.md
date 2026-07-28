# Deja

[![CI](https://github.com/Allen-Saji/deja/actions/workflows/ci.yml/badge.svg)](https://github.com/Allen-Saji/deja/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-111111.svg)](LICENSE)

Deja is a durable incident response agent. It diagnoses an alert, cites relevant precedent, records
what happened, and improves its next response from operator outcomes.

Built for the CockroachDB x AWS Hackathon.

[Open the live dashboard](https://deja-khaki.vercel.app)

## Why Deja

Most incident agents start every alert from zero. Their reasoning disappears when a worker times
out, prior postmortems remain disconnected from the current incident, and repeated alert noise
keeps reaching operators.

Deja treats memory as part of the execution model:

- Working memory checkpoints every graph node so an interrupted run can resume.
- Episodic memory retrieves similar completed incidents through CockroachDB C-SPANN.
- Procedural memory learns which duplicate notifications to suppress and which runbooks work.

The result is an agent whose diagnosis is traceable to stored evidence and whose behavior becomes
more useful as incidents accumulate.

## Architecture

![Deja implementation architecture](docs/architecture/deja-architecture.png)

An IAM-signed alert reaches a FastAPI service on AWS Lambda. The API reserves one durable run,
queues an asynchronous self-invocation, and returns HTTP 202. The worker claims a database lease,
loads the latest LangGraph checkpoint, and executes only the unfinished graph nodes:

1. `ingest` persists the alert.
2. `recall` embeds the incident with VoyageAI and retrieves relevant precedent with C-SPANN.
3. `triage` asks Groq for structured diagnosis and validates every cited incident ID.
4. `act` recommends a runbook or suppresses only a learned duplicate notification.
5. `writeback` completes the postmortem and records evidence for future runs.

CockroachDB Cloud is the system of record for incidents, runs, postmortems, checkpoints, vectors,
the noise ledger, and runbook outcomes. A separate Next.js dashboard and CockroachDB Managed MCP
connection use dedicated read-only access.

The `act` node is advisory. Deja never changes infrastructure and never skips incident processing.

## Durable memory

### Working memory

`CockroachDBSaver` writes a checkpoint after every graph node under the stable `run_id`. Lambda
retries claim the same execution lease and continue from the saved checkpoint instead of starting
another incident.

### Episodic memory

VoyageAI produces 1,024-dimensional postmortem embeddings. CockroachDB C-SPANN searches completed
incidents within the same service and alert type. Triage may cite only IDs returned by that search.

### Procedural memory

The noise ledger learns a stable duplicate only after three matching non-critical,
non-escalated observations. Runbooks use Laplace-smoothed efficacy scores from recorded operator
success and failure outcomes.

## Production evidence

The deployed system has been exercised through its real IAM-protected Lambda Function URL and
CockroachDB Cloud database.

| Capability | Verified evidence |
| --- | --- |
| Normal alert flow | `RUN-E1D6DD5025E8` queued and completed all five graph nodes |
| Timeout recovery | `RUN-591F981A5EDB` timed out before triage; the retry resumed at triage and completed in 2.966 seconds |
| Database node loss | The local three-node CockroachDB acceptance killed one node before triage and completed through the remaining quorum |
| Production observability | `RUN-3E482889BBA4` completed in 4.334 seconds with structured CloudWatch events from acceptance through completion |
| Read-only inspection | Managed MCP queried the live cluster through a scoped read-only principal |
| Public operations view | The Vercel dashboard serves a sanitized, auto-refreshing snapshot with no database or provider credentials |

Detailed read-only controls and verification queries are in
[`docs/observability/read-only-access.md`](docs/observability/read-only-access.md).

## Dashboard

Production: [deja-khaki.vercel.app](https://deja-khaki.vercel.app)

The dashboard shows the incident feed, graph-node and attempt traces, latency, memory lift, learned
noise patterns, and runbook efficacy. It queries CockroachDB only from the Next.js server boundary
and exposes no mutation endpoint.

```sh
cd dashboard
cp .env.example .env.local
# Set DEJA_DATABASE_URL to a read-only CockroachDB connection.
npm ci
npm run check
npm run dev
```

Vercel functions run in `bom1`, colocated with the Mumbai CockroachDB cluster.

## API

- `GET /health`: process health without external calls
- `GET /ready`: CockroachDB connectivity
- `POST /alerts`: reserve a run, queue execution, return HTTP 202
- `GET /runs/{run_id}`: persisted run and postmortem
- `GET /runs/{run_id}/attempts`: execution attempts and checkpoint resume positions
- `POST /runbooks`: create an enabled runbook with a neutral efficacy score
- `POST /runs/{run_id}/runbook-outcome`: record success or failure for the selected runbook

Example alert:

```json
{
  "service": "payments-api",
  "alert_type": "http-500-spike",
  "severity": "critical",
  "message": "HTTP 500 rate exceeded 18 percent after deploy",
  "labels": {
    "environment": "production",
    "region": "ap-south-1"
  }
}
```

## Local development

Requirements:

- Python 3.12
- `uv`
- Node.js 22 for the dashboard
- Docker for the three-node database acceptance

```sh
uv sync --frozen --extra dev --python 3.12
cp .env.example .env
```

Set `DATABASE_URL`, `GROQ_API_KEY`, and `VOYAGE_API_KEY` in `.env`, then load them without printing
their values:

```sh
set -a
. ./.env
set +a

.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/python scripts/live_smoke.py
.venv/bin/python scripts/memory_state_acceptance.py
make crdb-node-failure-acceptance
```

The exploratory checkpoint and vector experiments remain under `spikes/`:

```sh
.venv/bin/python spikes/s3_checkpoint_resume.py crash
.venv/bin/python spikes/s3_checkpoint_resume.py resume
.venv/bin/python spikes/s3_vectorstore.py
```

## Live acceptance

Invoke an IAM-protected Function URL with a signed request:

```sh
.venv/bin/deja-simulate https://FUNCTION_ID.lambda-url.ap-south-1.on.aws \
  --aws-profile deja \
  --aws-region ap-south-1

.venv/bin/python scripts/memory_replay_acceptance.py \
  https://FUNCTION_ID.lambda-url.ap-south-1.on.aws \
  --aws-profile deja \
  --aws-region ap-south-1

# Enable DEJA_CHAOS_ENABLED only for the controlled timeout acceptance window.
make lambda-timeout-acceptance
```

## Deployment

The deployment script creates or updates the ECR repository, Lambda execution role, container
function, asynchronous retry configuration, and IAM-protected Function URL.

```sh
set -a
. ./.env
set +a

AWS_PROFILE=deja AWS_REGION=ap-south-1 ./scripts/deploy.sh
```

## Project layout

```text
src/deja/          FastAPI service, LangGraph workflow, memory, and persistence
dashboard/         Read-only Next.js operations dashboard
scripts/           Deployment, smoke, replay, timeout, and node-loss acceptance
deploy/            Isolated three-node CockroachDB test environment
docs/              Architecture, observability, and submission material
tests/             Backend unit and contract tests
spikes/            Early checkpoint and vector-search experiments
```

## Security model

- The Lambda Function URL requires AWS IAM authentication.
- CockroachDB connections use TLS `verify-full` with the cloud root certificate in the image.
- Execution leases prevent concurrent duplicate delivery and expire for safe retry.
- Node effects are first-write-wins by run ID and node name.
- Groq output is schema-validated before it reaches the workflow.
- The dashboard and Managed MCP use a principal restricted to `SELECT` on nine exact tables.
- Browser responses contain no database URL, AWS credential, or provider key.

## Current limitations

- Deja recommends actions but does not execute infrastructure changes.
- Similarity recall is deliberately constrained by service and alert type.
- Noise suppression requires stable repeated observations and never suppresses critical alerts.
- Operator outcome capture is exposed through the API; a dedicated feedback UI is not included.

## License

[MIT](LICENSE)

# Deja

Deja is an incident response agent that remembers every run. It diagnoses alerts with Groq,
stores durable LangGraph checkpoints in CockroachDB, recalls prior postmortems through C-SPANN,
tracks repeated alert noise, and ranks runbooks from recorded operator outcomes.

Built for the CockroachDB x AWS Hackathon.

## Architecture

```text
alert simulator
    -> IAM-protected AWS Lambda Function URL
    -> FastAPI + Mangum
    -> LangGraph: ingest -> recall -> triage -> act -> writeback
         working memory: CockroachDBSaver checkpoints
         episodic memory: VoyageAI embeddings + CockroachDB C-SPANN
         procedural memory: outcome-ranked runbooks
         triage: Groq llama-3.3-70b-versatile
         system of record: incidents, runs, and postmortems in CockroachDB
```

The `act` node remains advisory. It can rank a runbook or suppress a duplicate notification, but
it never changes real infrastructure and never skips incident processing.

## Status

P2 memory implementation, deployment, and signed cloud acceptance completed on July 22, 2026.

- Real alert-to-postmortem workflow deployed to AWS Lambda in `ap-south-1`
- IAM-protected Function URL live
- Groq triage returns validated JSON
- CockroachDB stores relational run data and all LangGraph checkpoints
- TLS uses `verify-full` with the CockroachDB Cloud root certificate bundled in the image
- Local and live-cloud smoke tests pass
- Completed postmortems are embedded with `voyage-4-lite` at 1,024 dimensions
- C-SPANN recall is constrained by service and alert type
- Triage citations are checked against the incidents returned by recall
- Three stable non-critical, non-escalated observations suppress only duplicate notifications
- Runbooks use Laplace-smoothed efficacy scores from recorded success and failure outcomes
- Lambda runs ECR image `p2-20260722105040`

Signed cloud acceptance created novel run `RUN-7D10583858C2` in 3.336 seconds, then replayed the
same alert as `RUN-A78FDB9F0A38` in 1.234 seconds with a validated citation to
`INC-FFAD5AD49F1C`. These are single end-to-end observations, not a controlled latency benchmark.
The relational acceptance passed noise states `[false, false, true]`, kept the first run's
suppression decision stable on replay, survived five concurrent observations, and selected the
higher-efficacy runbook.

## API

- `GET /health`: process health without touching external services
- `GET /ready`: verifies CockroachDB connectivity
- `POST /alerts`: runs the complete P2 graph
- `GET /runs/{run_id}`: reads the persisted run and postmortem
- `POST /runbooks`: creates an enabled runbook with an initial neutral efficacy score
- `POST /runs/{run_id}/runbook-outcome`: records success or failure for the selected runbook

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

Python 3.12 and `uv` are required.

```sh
uv sync --extra dev --python 3.12
cp .env.example .env
```

Set `DATABASE_URL`, `GROQ_API_KEY`, and `VOYAGE_API_KEY` in `.env`, then load them without printing
their values:

```sh
set -a
. ./.env
set +a

.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/python scripts/live_smoke.py
.venv/bin/python scripts/p2_state_acceptance.py
```

The original P0 experiments remain under `spikes/`:

```sh
.venv/bin/python spikes/s3_checkpoint_resume.py crash
.venv/bin/python spikes/s3_checkpoint_resume.py resume
.venv/bin/python spikes/s3_vectorstore.py
```

## Deploy

The deployment script creates or updates the ECR repository, Lambda execution role, container
function, and IAM-protected Function URL.

```sh
set -a
. ./.env
set +a

AWS_PROFILE=deja AWS_REGION=ap-south-1 ./scripts/deploy.sh
```

Invoke the URL with a signed request:

```sh
.venv/bin/deja-simulate https://FUNCTION_ID.lambda-url.ap-south-1.on.aws \
  --aws-profile deja \
  --aws-region ap-south-1

.venv/bin/python scripts/p2_replay_acceptance.py \
  https://FUNCTION_ID.lambda-url.ap-south-1.on.aws \
  --aws-profile deja \
  --aws-region ap-south-1
```

## License

MIT

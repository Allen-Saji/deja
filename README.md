# Deja

Deja is an incident response agent that remembers every run. It diagnoses alerts with Groq,
stores durable LangGraph checkpoints in CockroachDB, and writes a structured incident record and
postmortem after each run.

Built for the CockroachDB x AWS Hackathon.

## Architecture

```text
alert simulator
    -> IAM-protected AWS Lambda Function URL
    -> FastAPI + Mangum
    -> LangGraph: ingest -> recall -> triage -> act -> writeback
         working memory: CockroachDBSaver checkpoints
         triage: Groq llama-3.3-70b-versatile
         system of record: incidents, runs, and postmortems in CockroachDB
```

The `act` node is deliberately safe in P1. It records one reversible recommendation but does not
change real infrastructure.

## Status

P1 walking skeleton completed on July 21, 2026.

- Real alert-to-postmortem workflow deployed to AWS Lambda in `ap-south-1`
- IAM-protected Function URL live
- Groq triage returns validated JSON
- CockroachDB stores relational run data and all LangGraph checkpoints
- TLS uses `verify-full` with the CockroachDB Cloud root certificate bundled in the image
- Local and live-cloud smoke tests pass

P2 will add C-SPANN precedent recall, the alert-noise ledger, and runbook efficacy ranking. The
`recall` node intentionally returns no precedents until that phase.

## API

- `GET /health`: process health without touching external services
- `GET /ready`: verifies CockroachDB connectivity
- `POST /alerts`: runs the complete P1 graph
- `GET /runs/{run_id}`: reads the persisted run and postmortem

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

Set `DATABASE_URL` and `GROQ_API_KEY` in `.env`, then load them without printing their values:

```sh
set -a
. ./.env
set +a

.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/python scripts/live_smoke.py
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
```

## License

MIT

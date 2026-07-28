# How to record the Deja submission demo

This runbook produces a repeatable demo in less than three minutes without exposing credentials.

## Prerequisites

- The public dashboard is healthy at https://deja-khaki.vercel.app.
- The local repository is on `main` and dependencies are installed.
- AWS profile `deja` can invoke the Deja Function URL.
- `DEJA_FUNCTION_URL` is set in the recording shell.
- The terminal font is at least 18 px and notifications are disabled.
- No `.env`, AWS configuration, Vercel inspector, or browser developer-tools storage panel is
  visible.

Verify presence without printing values:

```sh
test -n "${DEJA_FUNCTION_URL:-}" || {
  echo "DEJA_FUNCTION_URL is required"
  exit 1
}
AWS_PROFILE=deja aws sts get-caller-identity --query Account --output text >/dev/null
```

## Recording sequence

### 1. Open with the outcome

Open https://deja-khaki.vercel.app and say:

> Deja is incident response memory that survives failure. It remembers execution checkpoints,
> similar incidents, alert-noise evidence, and runbook outcomes in CockroachDB.

Keep the metric cards and recent runs visible.

### 2. Show a memory-assisted diagnosis

Select `RUN-DED9BC1C7367`.

Point to:

- the two cited precedents;
- the 5.602-second diagnosis time;
- the five completed workflow nodes;
- the advisory action outcome.

Say:

> This run retrieved two completed incidents through CockroachDB's distributed vector index. The
> model could cite only those retrieved IDs.

### 3. Submit a fresh signed alert

In a clean terminal, run:

```sh
.venv/bin/deja-simulate "$DEJA_FUNCTION_URL" \
  --aws-profile deja \
  --aws-region ap-south-1 \
  --service payments-api \
  --alert-type http-500-spike \
  --severity critical
```

Cut the provider wait if needed, but retain the initial queue response and final completed result.
Do not print environment variables.

Return to the dashboard and click Refresh. Select the new top run and show its durable ID,
workflow trace, and any cited precedent.

### 4. Show timeout recovery

Select `RUN-65FE655CA00C`.

Point to:

- attempt count 2;
- attempt one marked `lease_expired`;
- attempt two resumed from `triage`;
- final status `completed`.

Say:

> The first Lambda timed out after recall. The next invocation claimed the expired lease and
> resumed at triage. Completed node effects were not repeated.

Do not enable the chaos flag during the recording. Use the verified stored run.

### 5. Close on architecture and safety

Open `docs/architecture/deja-architecture.png`.

Trace:

1. IAM-signed alert to AWS Lambda.
2. Asynchronous worker through the five-node graph.
3. Checkpoints, incidents, vectors, noise, and runbooks in CockroachDB.
4. Read-only Managed MCP and dashboard access.

Close with:

> CockroachDB is the agent's execution memory and learning memory, not a demo datastore. Deja is
> advisory only, so operators keep control.

## Verification before upload

- Video duration is under 3:00.
- The public app URL is visible at least once.
- CockroachDB C-SPANN, Managed MCP, and AWS Lambda are each named and shown.
- The timeout attempt ledger is readable at normal playback speed.
- No secret, connection string, account ARN, browser token, or local path appears.
- Audio is understandable on a phone speaker.
- Upload is public on YouTube or Vimeo.
- The video URL works in a private browser window.

## Backup path

If the live alert provider is slow, skip the terminal step and use these stored runs:

- Cold diagnosis: `RUN-376DC3E77F40`, 40.940 seconds.
- Memory-assisted diagnosis: `RUN-DED9BC1C7367`, 5.602 seconds.
- Timeout recovery: `RUN-65FE655CA00C`, resumed from `triage`.

The dashboard remains a functional demo even when a model provider is unavailable.

## Troubleshooting

### The signed request is rejected

Confirm the profile and region without printing credentials:

```sh
AWS_PROFILE=deja aws sts get-caller-identity --query Account --output text >/dev/null
```

Then confirm `DEJA_FUNCTION_URL` is present and has no query or fragment.

### The dashboard does not show the new run

Wait for the simulator to print a completed result, then click Refresh. The snapshot is no-store
and reads the latest 50 runs.

### A provider call takes too long

Use the backup path. Do not spend recording time debugging an external provider.

## Related

- [Video script](video-script.md)
- [Judging map](judging-map.md)
- [Final submission checklist](final-checklist.md)

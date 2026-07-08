# Deja

An incident response agent that never forgets. Every alert becomes a run, and every run inherits the learnings of all previous runs: past incident precedents, alert noise history, and runbook success rates.

Built for the CockroachDB x AWS hackathon (Never-Forget Workflows track).

## How it works

```
alert -> AWS Lambda (FastAPI) -> LangGraph pipeline
         ingest -> recall -> triage -> act -> writeback
```

Three kinds of memory, all in one CockroachDB database:

- **Episodic**: postmortem embeddings with a C-SPANN vector index. New alerts recall similar past incidents and cite them.
- **Procedural**: runbook efficacy scores. The agent picks remediations by historical success rate.
- **Working**: LangGraph checkpoints via `langchain-cockroachdb`. If the process dies mid-run, the next invocation resumes from the last checkpoint instead of starting over.

## Status

Spike phase. `spikes/` contains the validation experiments:

- `s3_checkpoint_resume.py`: kills the process mid-run, proves a fresh process resumes from the CockroachDB checkpoint without re-running completed nodes.
- `s3_vectorstore.py`: vectorstore roundtrip plus C-SPANN index creation.

Run them against a local single-node CockroachDB:

```sh
docker run -d --name deja-crdb -p 26257:26257 -p 8081:8080 \
  cockroachdb/cockroach:latest start-single-node --insecure
docker exec deja-crdb cockroach sql --insecure -e "CREATE DATABASE deja"

uv venv .venv
uv pip install --python .venv/bin/python -r spikes/requirements.txt

.venv/bin/python spikes/s3_checkpoint_resume.py crash
.venv/bin/python spikes/s3_checkpoint_resume.py resume
.venv/bin/python spikes/s3_vectorstore.py
```

## License

MIT

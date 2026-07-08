"""S3 spike: prove LangGraph checkpoint resume on CockroachDB.

Run 1: python spikes/s3_checkpoint_resume.py crash   -> process dies mid-run, after ingest checkpointed
Run 2: python spikes/s3_checkpoint_resume.py resume  -> same thread_id resumes, ingest must NOT re-run
"""
import os
import sys
from pathlib import Path
from typing import TypedDict

from langchain_cockroachdb import CockroachDBSaver
from langgraph.graph import StateGraph, START, END

DB = os.environ.get("DATABASE_URL", "postgresql://root@localhost:26257/deja")
THREAD = {"configurable": {"thread_id": "run-001"}}
MARKER = Path(__file__).with_name("s3_ingest_runs.log")


class RunState(TypedDict):
    steps: list


def ingest(state: RunState) -> dict:
    with MARKER.open("a") as f:
        f.write("ingest\n")
    print("node: ingest")
    return {"steps": state["steps"] + ["ingest"]}


def triage(state: RunState) -> dict:
    if sys.argv[1] == "crash":
        print("!! simulating process kill mid-run (ingest already checkpointed)")
        sys.exit(137)
    print("node: triage")
    return {"steps": state["steps"] + ["triage"]}


def writeback(state: RunState) -> dict:
    print("node: writeback")
    return {"steps": state["steps"] + ["writeback"]}


g = StateGraph(RunState)
g.add_node("ingest", ingest)
g.add_node("triage", triage)
g.add_node("writeback", writeback)
g.add_edge(START, "ingest")
g.add_edge("ingest", "triage")
g.add_edge("triage", "writeback")
g.add_edge("writeback", END)

with CockroachDBSaver.from_conn_string(DB) as saver:
    saver.setup()
    app = g.compile(checkpointer=saver)
    if sys.argv[1] == "crash":
        MARKER.unlink(missing_ok=True)
        app.invoke({"steps": []}, THREAD)
    else:
        result = app.invoke(None, THREAD)  # None input = resume from last checkpoint
        ingest_runs = MARKER.read_text().count("ingest")
        print("final steps:", result["steps"])
        print("ingest executed", ingest_runs, "time(s) across both processes")
        assert result["steps"] == ["ingest", "triage", "writeback"], result["steps"]
        assert ingest_runs == 1, "ingest re-ran -> checkpoint resume FAILED"
        print("S3 CHECKPOINT RESUME: PASS")

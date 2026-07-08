"""S3 spike: CockroachDB vectorstore roundtrip + C-SPANN vector index.

Uses deterministic fake embeddings (no API key needed) - this tests the DB layer only.
Run: python spikes/s3_vectorstore.py
"""
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_cockroachdb import (
    CockroachDBEngine,
    CockroachDBVectorStore,
    CSPANNIndex,
)

# cockroachdb dialect (not vanilla postgresql) - CRDB's version string breaks the pg dialect;
# +psycopg (v3) gives the async driver the engine requires
DB = "cockroachdb+psycopg://root@localhost:26257/deja"
DIM = 384

engine = CockroachDBEngine.from_connection_string(DB)
emb = DeterministicFakeEmbedding(size=DIM)

engine.init_vectorstore_table("incident_precedents", vector_dimension=DIM)
vs = CockroachDBVectorStore(engine, emb, "incident_precedents")

postmortems = [
    "INC-001: payments-api 500 spike caused by exhausted db connection pool after deploy",
    "INC-002: checkout latency from redis eviction storm, fixed by raising maxmemory",
    "INC-003: cron job overlap double-charged invoices, fixed with advisory lock",
]
vs.add_texts(postmortems, metadatas=[{"incident": f"INC-00{i+1}"} for i in range(3)])
print(f"inserted {len(postmortems)} postmortems")

# roundtrip: identical text must come back rank 1 (deterministic embeddings)
hits = vs.similarity_search_with_score(postmortems[0], k=2)
top_doc, top_score = hits[0]
print("top hit:", top_doc.metadata, "score:", round(top_score, 4))
assert top_doc.metadata["incident"] == "INC-001", hits
print("VECTORSTORE ROUNDTRIP: PASS")

# C-SPANN index on the same table (v25.2+ feature)
vs.apply_vector_index(CSPANNIndex(name="precedent_cspann_idx"))
print("C-SPANN INDEX CREATE: PASS")

# search again, now through the index path
hits2 = vs.similarity_search("database connections exhausted during deploy", k=1)
print("post-index search hit:", hits2[0].metadata)
print("S3 VECTORSTORE: ALL PASS")

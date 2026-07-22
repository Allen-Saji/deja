from types import SimpleNamespace

from deja.memory import (
    VOYAGE_MAX_ATTEMPTS,
    VOYAGE_TIMEOUT_SECONDS,
    CockroachPrecedentMemory,
    alert_search_text,
    create_voyage_embeddings,
    precedent_document,
    vector_database_url,
)
from deja.models import Alert, TriageDecision


def alert() -> Alert:
    return Alert(
        service="payments-api",
        alert_type="http-500-spike",
        severity="critical",
        message="500s rose after deploy",
        labels={"region": "ap-south-1"},
    )


def decision() -> TriageDecision:
    return TriageDecision(
        diagnosis="Database connection pool saturation",
        confidence=0.9,
        severity="critical",
        recommended_action="Roll back the latest deploy",
        rationale="Pool waits rose after the deploy",
        escalate=True,
        postmortem_summary="The deploy exhausted the database connection pool.",
    )


class FakeStore:
    def __init__(self, *, distance: float = 0.12) -> None:
        self.added = None
        self.distance = distance

    def similarity_search_with_score(self, query, **kwargs):
        assert "500s rose after deploy" in query
        assert kwargs["filter"]["$and"] == [
            {"service": "payments-api"},
            {"alert_type": "http-500-spike"},
        ]
        metadata = {
            "incident_id": "INC-PREVIOUS",
            "run_id": "RUN-PREVIOUS",
            "fingerprint": "a" * 64,
            "service": "payments-api",
            "alert_type": "http-500-spike",
            "severity": "critical",
            "action_outcome": "recommendation_recorded_no_external_action",
        }
        return [(SimpleNamespace(metadata=metadata, page_content="prior summary"), self.distance)]

    def add_texts(self, texts, **kwargs):
        self.added = (texts, kwargs)


def test_memory_texts_are_stable_and_database_url_uses_cockroach_dialect() -> None:
    assert alert_search_text(alert()).startswith("service: payments-api")
    assert precedent_document(alert(), decision()).endswith(
        "postmortem: The deploy exhausted the database connection pool."
    )
    assert vector_database_url("postgresql://db") == "cockroachdb+psycopg://db"
    assert vector_database_url("sqlite://db") == "sqlite://db"


def test_memory_constructor_and_setup_are_idempotent(monkeypatch) -> None:
    class FakeEngine:
        initialized = []

        @classmethod
        def from_connection_string(cls, url, **kwargs):
            assert url == "cockroachdb+psycopg://db"
            assert kwargs == {"pool_size": 2, "max_overflow": 1}
            return cls()

        def init_vectorstore_table(self, table, **kwargs):
            self.initialized.append((table, kwargs))

    class SetupStore:
        def __init__(self, engine, embeddings, table):
            assert isinstance(engine, FakeEngine)
            assert embeddings == "embeddings"
            self.table = table
            self.indexes = []

        def apply_vector_index(self, index):
            self.indexes.append(index.name)

    monkeypatch.setattr("deja.memory.CockroachDBEngine", FakeEngine)
    monkeypatch.setattr("deja.memory.CockroachDBVectorStore", SetupStore)
    monkeypatch.setattr(
        "deja.memory.create_voyage_embeddings",
        lambda **_kwargs: "embeddings",
    )

    memory = CockroachPrecedentMemory(
        database_url="postgresql://db",
        api_key="test-key",
        model="voyage-4-lite",
    )
    memory.setup()
    memory.setup()

    assert len(memory._engine.initialized) == 1
    assert memory._store.indexes == ["deja_precedent_cspann_idx"]


def test_memory_recalls_typed_precedents_and_upserts_by_incident_id() -> None:
    store = FakeStore()
    memory = CockroachPrecedentMemory.__new__(CockroachPrecedentMemory)
    memory._store = store

    precedents = memory.recall(alert())
    memory.remember(
        alert=alert(),
        incident_id="INC-CURRENT",
        run_id="RUN-CURRENT",
        triage=decision(),
        action_outcome="recommendation_recorded_no_external_action",
    )

    assert precedents[0].incident_id == "INC-PREVIOUS"
    assert precedents[0].distance == 0.12
    assert store.added is not None
    assert store.added[1]["ids"] == ["INC-CURRENT"]


def test_memory_discards_distant_same_type_matches() -> None:
    memory = CockroachPrecedentMemory.__new__(CockroachPrecedentMemory)
    memory._store = FakeStore(distance=0.8)

    assert memory.recall(alert()) == []


def test_voyage_clients_use_bounded_timeouts() -> None:
    embeddings = create_voyage_embeddings(api_key="test-key", model="voyage-4-lite")

    assert embeddings._client._params["request_timeout"] == VOYAGE_TIMEOUT_SECONDS
    assert embeddings._aclient._params["request_timeout"] == VOYAGE_TIMEOUT_SECONDS
    assert embeddings._client.max_retries == VOYAGE_MAX_ATTEMPTS
    assert embeddings._aclient.max_retries == VOYAGE_MAX_ATTEMPTS

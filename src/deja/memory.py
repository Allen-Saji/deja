from __future__ import annotations

import json
from typing import Protocol

from langchain_cockroachdb import (
    CockroachDBEngine,
    CockroachDBVectorStore,
    CSPANNIndex,
)
from langchain_voyageai import VoyageAIEmbeddings
from voyageai import AsyncClient, Client

from deja.models import Alert, Precedent, TriageDecision

PRECEDENT_TABLE = "deja_precedent_vectors"
PRECEDENT_INDEX = "deja_precedent_cspann_idx"
VOYAGE_4_LITE_DIMENSION = 1_024
MAX_PRECEDENT_COSINE_DISTANCE = 0.35
VOYAGE_TIMEOUT_SECONDS = 5.0
VOYAGE_MAX_ATTEMPTS = 7


class EpisodicMemory(Protocol):
    def setup(self) -> None: ...

    def recall(self, alert: Alert, *, limit: int = 3) -> list[Precedent]: ...

    def remember(
        self,
        *,
        alert: Alert,
        incident_id: str,
        run_id: str,
        triage: TriageDecision,
        action_outcome: str,
    ) -> None: ...


def vector_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "cockroachdb+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "cockroachdb+psycopg://", 1)
    return database_url


def alert_search_text(alert: Alert) -> str:
    labels = json.dumps(alert.labels, sort_keys=True, separators=(",", ":"))
    return (
        f"service: {alert.service}\n"
        f"alert type: {alert.alert_type}\n"
        f"severity: {alert.severity}\n"
        f"labels: {labels}\n"
        f"observation: {alert.message}"
    )


def precedent_document(alert: Alert, triage: TriageDecision) -> str:
    return (
        f"service: {alert.service}\n"
        f"alert type: {alert.alert_type}\n"
        f"severity: {triage.severity}\n"
        f"diagnosis: {triage.diagnosis}\n"
        f"resolution: {triage.recommended_action}\n"
        f"postmortem: {triage.postmortem_summary}"
    )


def create_voyage_embeddings(*, api_key: str, model: str) -> VoyageAIEmbeddings:
    embeddings = VoyageAIEmbeddings(
        api_key=api_key,
        model=model,
        output_dimension=VOYAGE_4_LITE_DIMENSION,
    )
    embeddings._client = Client(
        api_key=api_key,
        max_retries=VOYAGE_MAX_ATTEMPTS,
        timeout=VOYAGE_TIMEOUT_SECONDS,
    )
    embeddings._aclient = AsyncClient(
        api_key=api_key,
        max_retries=VOYAGE_MAX_ATTEMPTS,
        timeout=VOYAGE_TIMEOUT_SECONDS,
    )
    return embeddings


class CockroachPrecedentMemory:
    def __init__(self, *, database_url: str, api_key: str, model: str) -> None:
        self._engine = CockroachDBEngine.from_connection_string(
            vector_database_url(database_url),
            pool_size=2,
            max_overflow=1,
        )
        embeddings = create_voyage_embeddings(api_key=api_key, model=model)
        self._store = CockroachDBVectorStore(
            self._engine,
            embeddings,
            PRECEDENT_TABLE,
        )
        self._is_setup = False

    def setup(self) -> None:
        if self._is_setup:
            return
        self._engine.init_vectorstore_table(
            PRECEDENT_TABLE,
            vector_dimension=VOYAGE_4_LITE_DIMENSION,
            id_type="STRING",
        )
        self._store.apply_vector_index(CSPANNIndex(name=PRECEDENT_INDEX))
        self._is_setup = True

    def recall(self, alert: Alert, *, limit: int = 3) -> list[Precedent]:
        matches = self._store.similarity_search_with_score(
            alert_search_text(alert),
            k=limit,
            filter={
                "$and": [
                    {"service": alert.service},
                    {"alert_type": alert.alert_type},
                ]
            },
        )
        return [
            Precedent.model_validate(
                {
                    **document.metadata,
                    "summary": document.page_content,
                    "distance": distance,
                }
            )
            for document, distance in matches
            if distance <= MAX_PRECEDENT_COSINE_DISTANCE
        ]

    def remember(
        self,
        *,
        alert: Alert,
        incident_id: str,
        run_id: str,
        triage: TriageDecision,
        action_outcome: str,
    ) -> None:
        self._store.add_texts(
            [precedent_document(alert, triage)],
            ids=[incident_id],
            metadatas=[
                {
                    "incident_id": incident_id,
                    "run_id": run_id,
                    "fingerprint": alert.fingerprint(),
                    "service": alert.service,
                    "alert_type": alert.alert_type,
                    "severity": triage.severity,
                    "action_outcome": action_outcome,
                }
            ],
        )

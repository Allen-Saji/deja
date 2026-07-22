from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from mangum import Mangum

from deja.config import Settings
from deja.models import (
    Alert,
    RunbookCreate,
    RunbookOutcome,
    RunbookScore,
    RunRecord,
    RunResult,
)

logger = logging.getLogger("deja")
app = FastAPI(title="Deja", version="0.1.0")


@lru_cache(maxsize=1)
def get_service() -> Any:
    from deja.memory import CockroachPrecedentMemory
    from deja.repository import IncidentRepository
    from deja.triage import GroqTriager
    from deja.workflow import IncidentService

    settings = Settings.from_env()
    repository = IncidentRepository(settings.database_url)
    return IncidentService(
        database_url=settings.database_url,
        repository=repository,
        triager=GroqTriager(api_key=settings.groq_api_key, model=settings.groq_model),
        memory=CockroachPrecedentMemory(
            database_url=settings.database_url,
            api_key=settings.voyage_api_key,
            model=settings.voyage_model,
        ),
    )


ServiceDependency = Annotated[Any, Depends(get_service)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "deja", "phase": "p2"}


@app.get("/ready")
def ready(service: ServiceDependency) -> dict[str, str]:
    try:
        service.readiness()
    except Exception as error:
        logger.error("readiness failed with %s", type(error).__name__)
        raise HTTPException(status_code=503, detail="service is not ready") from None
    return {"status": "ready"}


@app.post("/alerts", response_model=RunResult)
def submit_alert(
    alert: Alert,
    service: ServiceDependency,
) -> RunResult:
    try:
        return service.process_alert(alert)
    except Exception as error:
        logger.error("incident processing failed with %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="incident processing failed") from None


@app.get("/runs/{run_id}", response_model=RunRecord)
def get_run(run_id: str, service: ServiceDependency) -> RunRecord:
    try:
        record = service.get_run(run_id)
    except Exception as error:
        logger.error("run lookup failed with %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="run lookup failed") from None
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record


@app.post("/runbooks", response_model=RunbookScore, status_code=201)
def create_runbook(
    definition: RunbookCreate,
    service: ServiceDependency,
) -> RunbookScore:
    try:
        return service.create_runbook(definition)
    except Exception as error:
        logger.error("runbook write failed with %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="runbook write failed") from None


@app.post("/runs/{run_id}/runbook-outcome", response_model=RunbookScore)
def record_runbook_outcome(
    run_id: str,
    outcome: RunbookOutcome,
    service: ServiceDependency,
) -> RunbookScore:
    try:
        score = service.record_runbook_outcome(run_id, outcome.succeeded)
    except Exception as error:
        logger.error("runbook outcome write failed with %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="runbook outcome write failed") from None
    if score is None:
        raise HTTPException(status_code=404, detail="runbook selection not found")
    return score


@app.exception_handler(Exception)
async def opaque_error_handler(_request, error: Exception) -> JSONResponse:
    logger.error("request failed with %s", type(error).__name__)
    return JSONResponse(status_code=500, content={"detail": "incident processing failed"})


handler = Mangum(app, lifespan="off")

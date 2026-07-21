from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from mangum import Mangum

from deja.config import Settings
from deja.models import Alert, RunRecord, RunResult
from deja.repository import IncidentRepository
from deja.triage import GroqTriager
from deja.workflow import IncidentService

logger = logging.getLogger("deja")
app = FastAPI(title="Deja", version="0.1.0")


@lru_cache(maxsize=1)
def get_service() -> IncidentService:
    settings = Settings.from_env()
    repository = IncidentRepository(settings.database_url)
    return IncidentService(
        database_url=settings.database_url,
        repository=repository,
        triager=GroqTriager(api_key=settings.groq_api_key, model=settings.groq_model),
    )


ServiceDependency = Annotated[IncidentService, Depends(get_service)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "deja", "phase": "p1"}


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


@app.exception_handler(Exception)
async def opaque_error_handler(_request, error: Exception) -> JSONResponse:
    logger.error("request failed with %s", type(error).__name__)
    return JSONResponse(status_code=500, content={"detail": "incident processing failed"})


handler = Mangum(app, lifespan="off")

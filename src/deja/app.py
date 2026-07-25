from __future__ import annotations

import asyncio
import logging
import uuid
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from mangum import Mangum

from deja.config import Settings
from deja.models import (
    Alert,
    RunAccepted,
    RunAttemptRecord,
    RunbookCreate,
    RunbookOutcome,
    RunbookScore,
    RunExecutionEvent,
    RunRecord,
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
        execution_lease_seconds=settings.execution_lease_seconds,
    )


ServiceDependency = Annotated[Any, Depends(get_service)]


@lru_cache(maxsize=1)
def get_dispatcher() -> Any:
    from deja.execution import InlineDispatcher, LambdaDispatcher, lambda_function_name

    function_name = lambda_function_name()
    if function_name:
        return LambdaDispatcher(function_name=function_name)
    return InlineDispatcher(
        lambda event: get_service().execute_run(
            event,
            execution_token=f"INLINE-{event.run_id}",
        )
    )


DispatcherDependency = Annotated[Any, Depends(get_dispatcher)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "deja", "phase": "p3"}


@app.get("/ready")
def ready(service: ServiceDependency) -> dict[str, str]:
    try:
        service.readiness()
    except Exception as error:
        logger.error("readiness failed with %s", type(error).__name__)
        raise HTTPException(status_code=503, detail="service is not ready") from None
    return {"status": "ready"}


@app.post(
    "/alerts",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_alert(
    alert: Alert,
    service: ServiceDependency,
    dispatcher: DispatcherDependency,
) -> RunAccepted:
    accepted: RunAccepted | None = None
    try:
        accepted, event = service.prepare_alert(alert)
        dispatcher.dispatch(event)
        return accepted
    except Exception as error:
        if accepted is not None:
            try:
                service.fail_dispatch(accepted.run_id, type(error).__name__)
            except Exception:
                logger.error("dispatch failure persistence also failed")
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


@app.get("/runs/{run_id}/attempts", response_model=list[RunAttemptRecord])
def get_run_attempts(
    run_id: str,
    service: ServiceDependency,
) -> list[RunAttemptRecord]:
    try:
        attempts = service.get_run_attempts(run_id)
    except Exception as error:
        logger.error("run attempt lookup failed with %s", type(error).__name__)
        raise HTTPException(status_code=500, detail="run attempt lookup failed") from None
    if not attempts and service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return attempts


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


mangum_handler = Mangum(app, lifespan="off")


def ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def handler(event: Any, context: Any) -> Any:
    from deja.execution import TimeoutOnceInjector, is_run_execution_event

    if not is_run_execution_event(event):
        ensure_event_loop()
        return mangum_handler(event, context)

    execution_event = RunExecutionEvent.model_validate(event)
    service = get_service()
    settings = Settings.from_env()
    failure_hook = TimeoutOnceInjector(
        event=execution_event,
        claim_once=service.claim_chaos_injection,
        lambda_context=context,
        enabled=settings.chaos_enabled,
    )
    result = service.execute_run(
        execution_event,
        execution_token=f"{context.aws_request_id}-{uuid.uuid4().hex}",
        failure_hook=failure_hook,
    )
    return {
        "run_id": execution_event.run_id,
        "status": result.status if result else "duplicate_in_flight",
    }

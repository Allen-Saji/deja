from __future__ import annotations

import json
import os
from functools import lru_cache
from time import sleep
from typing import Any, Protocol

from deja.models import RunExecutionEvent


class RunDispatcher(Protocol):
    def dispatch(self, event: RunExecutionEvent) -> None: ...


class LambdaDispatcher:
    def __init__(self, *, function_name: str) -> None:
        if not function_name:
            raise ValueError("Lambda function name is required")
        self._function_name = function_name

    @staticmethod
    @lru_cache(maxsize=1)
    def _client() -> Any:
        import boto3

        return boto3.client("lambda")

    def dispatch(self, event: RunExecutionEvent) -> None:
        response = self._client().invoke(
            FunctionName=self._function_name,
            InvocationType="Event",
            Payload=json.dumps(event.model_dump(mode="json"), separators=(",", ":")).encode(),
        )
        if response.get("StatusCode") != 202:
            raise RuntimeError("Lambda did not accept the asynchronous run")


class InlineDispatcher:
    def __init__(self, execute) -> None:
        self._execute = execute

    def dispatch(self, event: RunExecutionEvent) -> None:
        self._execute(event)


class TimeoutOnceInjector:
    def __init__(
        self,
        *,
        event: RunExecutionEvent,
        claim_once,
        lambda_context: Any,
        enabled: bool,
    ) -> None:
        self._event = event
        self._claim_once = claim_once
        self._lambda_context = lambda_context
        self._enabled = enabled

    def __call__(self, run_id: str, before_node: str) -> None:
        chaos = self._event.chaos
        if chaos is None or chaos.mode != "timeout_once" or chaos.before_node != before_node:
            return
        if not self._enabled:
            raise RuntimeError("chaos injection is disabled")
        if not self._claim_once(run_id, before_node):
            return
        remaining_seconds = max(
            0.0,
            self._lambda_context.get_remaining_time_in_millis() / 1_000,
        )
        sleep(remaining_seconds + 1)


def is_run_execution_event(event: Any) -> bool:
    return isinstance(event, dict) and event.get("event_type") == "deja.run.execute"


def lambda_function_name() -> str:
    return os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "").strip()

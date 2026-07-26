import json
import logging

from deja.observability import JsonFormatter, log_event


def test_json_formatter_emits_only_allowlisted_context() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="deja",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ignored message",
        args=(),
        exc_info=None,
    )
    record.event = "run.completed"
    record.run_id = "RUN-TEST"
    record.database_url = "sensitive-value-must-not-appear"

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "run.completed"
    assert payload["run_id"] == "RUN-TEST"
    assert "database_url" not in payload
    assert "sensitive-value-must-not-appear" not in json.dumps(payload)


def test_log_event_drops_unknown_fields(caplog) -> None:
    logger = logging.getLogger("deja-test-observability")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(
            logger,
            "alert.accepted",
            run_id="RUN-TEST",
            credential="must-not-log",
        )

    assert caplog.records[0].run_id == "RUN-TEST"
    assert not hasattr(caplog.records[0], "credential")

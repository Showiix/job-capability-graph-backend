import json
import logging

from app.core.logging import JSONFormatter
from app.core.middleware import request_id_context


def test_json_formatter_includes_request_id_without_exception_text() -> None:
    token = request_id_context.set("req_logging")
    try:
        record = logging.LogRecord(
            name="app.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="safe message",
            args=(),
            exc_info=None,
        )
        payload = json.loads(JSONFormatter().format(record))
    finally:
        request_id_context.reset(token)

    assert payload["level"] == "ERROR"
    assert payload["message"] == "safe message"
    assert payload["request_id"] == "req_logging"

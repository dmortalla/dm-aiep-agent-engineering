"""Fresh-process SDK test seam: no vendor registry mutation or hosted transport."""

import json
import logging
import socket
import sys
from unittest.mock import patch

from harness_engineering import _offline_observability_worker as worker
from harness_engineering.observability import TelemetryEvent


def main() -> None:
    """Exercise one genuine SDK lifecycle with counted zero-network assertions."""
    logging.disable(logging.CRITICAL)
    attempts = 0

    def denied(*args: object, **kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("Offline SDK probe attempted a socket operation.")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied
    vendor, phase = sys.argv[1:]
    events = tuple(TelemetryEvent.model_validate_json(json.dumps(item))
                   for item in json.loads(sys.stdin.read(262144)))
    if vendor == "langsmith":
        from langsmith import Client

        target = Client
        method = {"construction": "__init__", "create": "create_run", "update": "update_run",
                  "flush": "flush", "close": "close"}
        projection = worker.langsmith_projection
    else:
        from langfuse import Langfuse, LangfuseSpan

        target = LangfuseSpan if phase == "update" else Langfuse
        method = {"construction": "__init__", "create": "start_observation", "update": "end",
                  "flush": "flush", "close": "shutdown"}
        projection = worker.langfuse_projection

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("SECRET-PROMPT-OUTPUT-CREDENTIAL-EXCEPTION-SENTINEL")

    if phase in method:
        with patch.object(target, method[phase], fail):
            try:
                projection(events)
            except worker.ProjectionFailure as error:
                assert error.__cause__ is None
                assert error.__suppress_context__
                result = {"failure": str(error)}
            else:
                raise AssertionError("Expected SDK phase failure was not observed.")
    else:
        result = {"records": projection(events)}
        if phase == "repeat":
            try:
                projection(events)
            except worker.ProjectionFailure as error:
                result["repeat_failure"] = str(error)
    result["network_attempts"] = attempts
    print(json.dumps(result))


if __name__ == "__main__":
    main()

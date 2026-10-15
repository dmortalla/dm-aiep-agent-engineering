"""Framework-independent bounded reviewer exercise over accepted application interfaces."""

import asyncio
import json
from collections import deque
from dataclasses import asdict
from uuid import uuid4

from module10_ai import InferenceRequest, InferenceService
from module10_ai.errors import ContractError
from module10_ai.execution import JobTimeout, LocalExecution, QueueUnavailable
from module10_ai.telemetry import CORRELATION, Telemetry, correlation_id, failure_category


async def exercise(text: str, keyword_limit: int = 3,
                   service: InferenceService | None = None) -> dict[str, object]:
    """Run two sequential real jobs, then close all owned asynchronous resources.

    Args:
        text: Untrusted reviewer text validated by the accepted domain contract.
        keyword_limit: Accepted keyword bound, validated without coercion.
        service: Trusted injection for deterministic failure testing.

    Returns:
        Detached presentation evidence or a fixed safe error, never exception details.
    """
    records: deque[str] = deque(maxlen=32)
    observer = Telemetry(records.append)
    execution = LocalExecution(InferenceService() if service is None else service,
                               telemetry=observer)
    token = CORRELATION.set(correlation_id(uuid4().hex))
    report: dict[str, object] = {"evidence": "local-deterministic"}
    deadline = asyncio.timeout(12)
    try:
        request = InferenceRequest(text, keyword_limit)
        await execution.start()
        report["readiness_during_exercise"] = execution.accepting
        report["configuration"] = asdict(execution.config)
        runs = []
        async with deadline:
            for _ in range(2):
                job = execution.submit(request)
                admitted = job.state.value
                result = await job.result()
                runs.append({"admission": admitted, "outcome": job.state.value,
                             "result": asdict(result), "cache": asdict(execution.cache.stats())})
        report["runs"] = runs
    except ContractError:
        report["error"] = "Enter 1–4096 nonblank characters and a keyword limit from 1 to 10."
    except JobTimeout:
        report["error"] = "The bounded exercise timed out. Try again."
    except TimeoutError as exc:
        if deadline.expired():
            report["error"] = "The bounded exercise timed out. Try again."
        else:
            observer.event("application.failure", status="failure", category=failure_category(exc))
            report["error"] = "The local application could not complete this exercise."
    except QueueUnavailable:
        report["error"] = "Local execution capacity is unavailable. Try again."
    except Exception as exc:
        # Genuine presentation boundary: retain only an accepted diagnostic category.
        observer.event("application.failure", status="failure", category=failure_category(exc))
        report["error"] = "The local application could not complete this exercise."
    finally:
        await execution.close()
        report["accepting_after_cleanup"] = execution.accepting
        report["queue_after_cleanup"] = asdict(execution.stats())
        report["metrics"] = observer.snapshot()
        report["events"] = [json.loads(record) for record in records]
        CORRELATION.reset(token)
    return report

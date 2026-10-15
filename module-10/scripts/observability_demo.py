"""Print bounded local deterministic observability evidence without cloud services."""

import asyncio
import json
from collections import deque

from module10_ai import InferenceRequest, InferenceService
from module10_ai.execution import LocalExecution
from module10_ai.telemetry import CORRELATION, Telemetry, correlation_id


async def main() -> None:
    """Exercise one cold and one warm job and print safe bounded evidence."""
    records: deque[str] = deque(maxlen=32)
    telemetry = Telemetry(records.append)
    execution = LocalExecution(InferenceService(), telemetry=telemetry)
    token = CORRELATION.set(correlation_id("local-review-request"))
    await execution.start()
    try:
        for _ in range(2):
            await execution.infer(InferenceRequest("Beta alpha beta gamma"))
    finally:
        await execution.close()
        CORRELATION.reset(token)
    print(
        json.dumps(
            {"events": [json.loads(line) for line in records], "metrics": telemetry.snapshot()},
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())

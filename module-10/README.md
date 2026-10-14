# Module 10 inference core — Story 10.2

This standalone Python 3.12 package supplies the application core for later
FastAPI and Streamlit layers. It has no runtime dependencies and performs no
network calls, credential loading, logging, or privileged actions.

From `module-10/`, install the module-local environment with `uv sync --locked
--python 3.12`. The committed `uv.lock` fixes development dependency resolution;
Hatchling builds the installable `src/module10_ai` package. Ruff and pytest are
development tools only. Standard-library frozen dataclasses provide sufficient
typed validation for this small contract; Pydantic and web frameworks are not
needed for this story.

The deterministic runtime counts Unicode alphabetic words, ignoring numbers,
punctuation, and underscores. It lowercases before tokenization, ranks words by
descending frequency and then alphabetical order, and returns at most the
requested keyword limit. This is lexical fixture analysis, not live AI generation.
The same input produces the same structured output; no timestamps or random values
enter the result.

```python
import asyncio
from dataclasses import asdict
from module10_ai import InferenceRequest, InferenceService

result = asyncio.run(
    InferenceService().infer(InferenceRequest("Beta alpha beta gamma", keyword_limit=3))
)
print(asdict(result))
# {'word_count': 4, 'keywords': ('beta', 'alpha', 'gamma'), 'evidence': 'deterministic'}
```

Requests accept 1–4096 characters of nonblank text and a strict integer keyword
limit of 1–10. Configuration can reduce the input ceiling; unsupported modes fail
closed. Boolean values do not count as integers. Contracts are immutable and do
not coerce input. The service revalidates requests and provider results, checks
request-specific output bounds, and rejects evidence inconsistent with its
deterministic configuration. Local-runtime and live-cloud labels exist solely
to distinguish future evidence; neither mode is implemented or authorized here.

The asynchronous `InferenceRuntime` protocol supports trusted provider injection
without HTTP or UI imports. Execution is one bounded deterministic pass, with no
retry loop or external cost. Async orchestration, queueing, service deadlines,
cache behavior, and concurrency controls remain later-story work.

Invalid caller input raises `ContractError`; invalid configuration raises
`ConfigurationError`. Expected provider `RuntimeFailure` or `ContractError`
failures become `InferenceFailure`, preserving causal context. Malformed provider
results also become `InferenceFailure`. Unexpected programming defects and caller
cancellation propagate. Public failure messages never interpolate input/provider
details, and request/result reprs omit text/keywords. Exception causes are internal
diagnostic context: a future API must not serialize tracebacks or causes to clients.
Keyword output remains untrusted user-derived data and may be sensitive; a future
presentation layer must escape it and avoid logging raw content. It grants no
deployment, rollback, or infrastructure authority.

Run the gates sequentially, stopping at the first failure:

```powershell
.venv/Scripts/ruff.exe check .
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m compileall src tests
```

See [Story 10.2 evidence](docs/STORY_10_2.md) for current verification and scope.
This core is functionally complete for Story 10.2; the Module 10 production
deployment and full reviewer experience remain unproven.

"""Application boundary validates input and output without HTTP or UI dependencies."""

from module10_ai.config import RuntimeConfig
from module10_ai.contracts import EvidenceClass, InferenceRequest, InferenceResult
from module10_ai.errors import ConfigurationError, ContractError, InferenceFailure, RuntimeFailure
from module10_ai.runtime import DeterministicRuntime, InferenceRuntime


class InferenceService:
    """Inference orchestration with explicit configuration and provider injection."""

    def __init__(
        self, config: RuntimeConfig | None = None, runtime: InferenceRuntime | None = None,
    ) -> None:
        """Bind trusted configuration and a provider, defaulting to no-key execution.

        Args:
            config: Validated deterministic configuration.
            runtime: Trusted provider implementation, or deterministic default.

        Raises:
            ConfigurationError: Configuration is not the required contract.
        """
        self._config = RuntimeConfig() if config is None else config
        if type(self._config) is not RuntimeConfig:
            raise ConfigurationError("Service requires RuntimeConfig.")
        self._config.__post_init__()
        self._runtime = DeterministicRuntime() if runtime is None else runtime

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Execute once and validate untrusted provider output before returning it.

        Args:
            request: Validated domain request.

        Returns:
            Validated deterministic analysis data, with no privileged authority.

        Raises:
            ContractError: Caller input is invalid or exceeds configured bounds.
            InferenceFailure: Expected runtime failure or malformed provider output.
        """
        if type(request) is not InferenceRequest:
            raise ContractError("Service requires an InferenceRequest.")
        request.__post_init__()
        if len(request.text) > self._config.max_text_characters:
            raise ContractError("Text exceeds the configured runtime ceiling.")
        try:
            result = await self._runtime.infer(request)
        except (RuntimeFailure, ContractError) as exc:
            raise InferenceFailure(
                "Inference failed; check provider availability or contract."
            ) from exc
        try:
            if type(result) is not InferenceResult:
                raise ContractError("Provider must return InferenceResult.")
            result.__post_init__()
            if result.evidence is not EvidenceClass.DETERMINISTIC:
                raise ContractError("Provider evidence conflicts with deterministic configuration.")
            if len(result.keywords) > request.keyword_limit:
                raise ContractError("Provider exceeds requested keyword limit.")
        except ContractError as exc:
            raise InferenceFailure("Provider returned an invalid inference result.") from exc
        return result

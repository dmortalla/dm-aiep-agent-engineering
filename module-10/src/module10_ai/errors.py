"""Safe public failures; messages never interpolate untrusted payloads."""


class ContractError(ValueError):
    """Request or result violates the typed inference contract."""


class ConfigurationError(ValueError):
    """Trusted runtime configuration is invalid or unsupported."""


class RuntimeFailure(RuntimeError):
    """Provider reports an expected execution failure."""


class InferenceFailure(RuntimeError):
    """Application cannot return a validated inference result."""

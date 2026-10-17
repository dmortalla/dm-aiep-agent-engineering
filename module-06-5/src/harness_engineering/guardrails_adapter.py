"""Additive local Guardrails AI schema validation; never inference or authority.

The verified 0.11.0 low-level payload validator returns None on success and
raises SchemaValidationError on rejection. No Guard, validator hub, re-ask,
repair, user-supplied schema/reference, or provider callback is accepted.
"""

import importlib
from importlib.metadata import PackageNotFoundError, version
from types import ModuleType

from harness_engineering.errors import ContractValidationError
from harness_engineering.providers import ProviderOutputRejected, _units


class GuardrailsConfigurationError(ContractValidationError):
    """Install the locked guardrails extra or restore the supported API."""


def _load() -> ModuleType:
    missing = False
    try:
        installed = version("guardrails-ai")
    except PackageNotFoundError:
        missing = True
    if missing:
        raise GuardrailsConfigurationError("Install the Module 6.5 locked guardrails extra.")
    if installed != "0.11.0":
        raise GuardrailsConfigurationError("Guardrails AI requires the verified locked 0.11.0 API.")
    try:
        module = importlib.import_module("guardrails.schema.validator")
    except ModuleNotFoundError as exc:
        if exc.name != "guardrails":
            raise  # Broken transitive imports are integration defects, not optional absence.
        missing = True
    if missing:
        raise GuardrailsConfigurationError("Install the Module 6.5 locked guardrails extra.")
    error = getattr(module, "SchemaValidationError", None)
    if (
        not callable(getattr(module, "validate_payload", None))
        or not isinstance(error, type)
        or not issubclass(error, Exception)
    ):
        raise GuardrailsConfigurationError(
            "Restore the locked Guardrails AI schema validation API."
        )
    return module


class GuardrailsTextValidator:
    """Opt-in nonblank text check using the actual local framework schema API.

    Construct at trusted bootstrap, outside the invocation deadline. The
    framework receives only a disposable text payload and a fixed local schema.
    It cannot replace text or return application control fields. Python package
    code is trusted integration code, not an in-process security sandbox.
    """

    def __init__(self) -> None:
        """Verify the optional locked dependency and supported API without inference."""
        self._framework = _load()

    def validate(self, text: str) -> None:
        """Reject invalid/nonblank text without returning content or diagnostics.

        Args:
            text: Already application-bounded, still untrusted model text.

        Raises:
            ProviderOutputRejected: For content/schema rejection or malformed results.
            Exception: Unexpected integration/programming defects propagate unchanged.
        """
        if type(text) is not str or len(text) > 20_000 or _units(text) > 2_000:
            raise ProviderOutputRejected("Guardrails input exceeds the application text profile.")
        rejected = False
        try:
            outcome = self._framework.validate_payload(
                {"text": text},
                {
                    "type": "object",
                    "required": ["text"],
                    "additionalProperties": False,
                    "properties": {
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 2_000,
                            "pattern": r"\S",
                        },
                    },
                },
                validate_subschema=False,
            )
        except self._framework.SchemaValidationError:
            rejected = True
        # Raise outside the exception scope: raw framework fields contain text.
        if rejected:
            raise ProviderOutputRejected("Guardrails rejected the application text profile.")
        if outcome is not None:
            raise ProviderOutputRejected("Guardrails returned an unsupported validation result.")

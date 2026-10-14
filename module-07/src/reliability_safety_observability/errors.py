"""Application-specific exceptions for Module 7 boundaries."""


class ModuleSevenError(Exception):
    """Base exception for expected Module 7 application failures."""


class ConfigurationError(ModuleSevenError):
    """Raised when runtime configuration violates a required invariant."""


class ContractValidationError(ModuleSevenError):
    """Raised when data cannot safely cross a typed application boundary."""


class AuthorizationDeniedError(ModuleSevenError):
    """Raised when application-owned authorization does not permit an action."""


class SafetyProviderError(ModuleSevenError):
    """Raised when a safety provider cannot produce a trustworthy result."""

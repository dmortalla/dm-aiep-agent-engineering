"""Application-owned exception hierarchy for Module 8."""


class EnterpriseIntegrationError(Exception):
    """Base exception for expected enterprise-integration failures."""


class ContractValidationError(EnterpriseIntegrationError):
    """Raised when untrusted data violates an application contract."""


class ConfigurationError(EnterpriseIntegrationError):
    """Raised when application configuration is invalid."""


class AuthorizationError(EnterpriseIntegrationError):
    """Raised when an operation lacks application-owned authorization."""

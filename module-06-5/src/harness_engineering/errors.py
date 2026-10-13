"""Domain-specific exceptions for the governed agent harness."""


class HarnessError(Exception):
    """Base exception for expected harness failures."""


class ContractValidationError(HarnessError):
    """Raised when data cannot satisfy a harness domain contract."""


class BudgetExceededError(HarnessError):
    """Raised when execution would exceed an enforced runtime budget."""


class AuthorityViolationError(HarnessError):
    """Raised when an operation attempts to exceed granted authority."""


class ToolExecutionError(HarnessError):
    """Raised when an authorized handler fails without a valid result."""


class ToolTimeoutError(BudgetExceededError):
    """Raised when an invocation exceeds its application deadline."""

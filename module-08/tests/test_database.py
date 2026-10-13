"""Tests for the SQLite enterprise customer capability."""

from pathlib import Path

import pytest

from mcp_enterprise_integration.database import CustomerRepository
from mcp_enterprise_integration.errors import EnterpriseIntegrationError


@pytest.fixture
def repository(tmp_path: Path) -> CustomerRepository:
    """Create an isolated deterministic customer repository."""
    repo = CustomerRepository(tmp_path / "customers.db")
    repo.initialize()
    return repo


def test_repository_returns_sanitized_customer(
    repository: CustomerRepository,
) -> None:
    """Return only the approved enterprise customer fields."""
    customer = repository.get_customer("CUST-001")

    assert customer is not None
    assert customer.customer_id == "CUST-001"
    assert customer.name == "Northstar Logistics"
    assert customer.segment == "Enterprise"
    assert customer.region == "South"
    assert customer.account_status == "active"
    assert set(customer.model_dump()) == {
        "customer_id",
        "name",
        "segment",
        "region",
        "account_status",
    }


def test_repository_returns_none_for_unknown_customer(
    repository: CustomerRepository,
) -> None:
    """Handle a valid but unknown customer identifier deterministically."""
    assert repository.get_customer("CUST-999") is None


def test_repository_list_is_bounded(repository: CustomerRepository) -> None:
    """Enforce the explicit maximum result-set boundary."""
    assert len(repository.list_customers(limit=2)) == 2

    with pytest.raises(ValueError, match="between 1 and 50"):
        repository.list_customers(limit=0)

    with pytest.raises(ValueError, match="between 1 and 50"):
        repository.list_customers(limit=51)


def test_lookup_is_not_vulnerable_to_identifier_sql_injection(
    repository: CustomerRepository,
) -> None:
    """Treat the identifier as data rather than executable SQL."""
    malicious = "CUST-001' OR 1=1 --"

    assert repository.get_customer(malicious) is None
    assert len(repository.list_customers()) == 3


def test_initialization_is_idempotent(repository: CustomerRepository) -> None:
    """Allow deterministic initialization without duplicating seed records."""
    repository.initialize()

    assert len(repository.list_customers()) == 3


def test_database_failure_preserves_causal_error(tmp_path: Path) -> None:
    """Translate SQLite failures at the enterprise integration boundary."""
    repository = CustomerRepository(tmp_path / "missing" / "customers.db")

    with pytest.raises(EnterpriseIntegrationError) as captured:
        repository.initialize()

    assert captured.value.__cause__ is not None

def test_repository_releases_database_file(tmp_path: Path) -> None:
    """Release SQLite handles after repository operations."""
    database_path = tmp_path / "customers.db"
    repository = CustomerRepository(database_path)
    repository.initialize()

    assert repository.get_customer("CUST-001") is not None
    assert repository.list_customers(limit=2)

    database_path.unlink()

    assert not database_path.exists()

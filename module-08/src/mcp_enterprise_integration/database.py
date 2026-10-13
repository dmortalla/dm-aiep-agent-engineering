"""SQLite-backed enterprise customer capability."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from mcp_enterprise_integration.errors import EnterpriseIntegrationError

CustomerIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class CustomerRecord(BaseModel):
    """Sanitized customer data safe for the enterprise integration boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: CustomerIdentifier
    name: str
    segment: str
    region: str
    account_status: str


class CustomerRepository:
    """Provide bounded read-only customer access through SQLite."""

    def __init__(self, database_path: Path) -> None:
        """Initialize the repository.

        Args:
            database_path: SQLite database file used by this repository.
        """
        self._database_path = database_path

    def initialize(self) -> None:
        """Create and deterministically seed the local enterprise database.

        Raises:
            EnterpriseIntegrationError: If database initialization fails.
        """
        try:
            with closing(sqlite3.connect(self._database_path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS customers (
                        customer_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        segment TEXT NOT NULL,
                        region TEXT NOT NULL,
                        account_status TEXT NOT NULL
                    )
                    """
                )
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO customers (
                        customer_id, name, segment, region, account_status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("CUST-001", "Northstar Logistics", "Enterprise", "South", "active"),
                        ("CUST-002", "Blue River Health", "Mid-Market", "West", "active"),
                        ("CUST-003", "Summit Retail Group", "Enterprise", "East", "review"),
                    ],
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise EnterpriseIntegrationError(
                f"Unable to initialize enterprise customer database: {exc}"
            ) from exc

    def get_customer(self, customer_id: CustomerIdentifier) -> CustomerRecord | None:
        """Return one sanitized customer record by identifier.

        Args:
            customer_id: Exact customer identifier to retrieve.

        Returns:
            The validated customer record, or None when no record exists.

        Raises:
            EnterpriseIntegrationError: If the database query fails.
        """
        try:
            with closing(sqlite3.connect(self._database_path)) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    """
                    SELECT customer_id, name, segment, region, account_status
                    FROM customers
                    WHERE customer_id = ?
                    """,
                    (customer_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise EnterpriseIntegrationError(
                f"Unable to query enterprise customer database: {exc}"
            ) from exc

        if row is None:
            return None

        return CustomerRecord.model_validate(dict(row))

    def list_customers(self, limit: int = 10) -> list[CustomerRecord]:
        """Return a bounded list of sanitized customer records.

        Args:
            limit: Maximum records to return, from 1 through 50.

        Returns:
            Validated customer records ordered by identifier.

        Raises:
            ValueError: If the requested limit is outside the safe range.
            EnterpriseIntegrationError: If the database query fails.
        """
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        try:
            with closing(sqlite3.connect(self._database_path)) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT customer_id, name, segment, region, account_status
                    FROM customers
                    ORDER BY customer_id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise EnterpriseIntegrationError(
                f"Unable to list enterprise customers: {exc}"
            ) from exc

        return [CustomerRecord.model_validate(dict(row)) for row in rows]

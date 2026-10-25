"""Story 13: explicit human live-execution authorization and cost exposure bounds.

A live provider call requires an exact ``LiveExecutionAuthorization`` installed
by trusted application bootstrap after a separate human cost/credential
decision. Nothing generated, retrieved, serialized, or credential-derived can
produce one: the runtime accepts only the exact type, never a mapping or JSON.
Prices are human-approved upper-bound tariffs for exposure gating, not billing.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_engineering.config import SUPPORTED_LIVE_MODELS, LiveProvider
from harness_engineering.domain import Identifier
from harness_engineering.errors import AuthorityViolationError

MAX_AUTHORIZATION_WINDOW = timedelta(days=7)
# Conservative per-request framing allowance added to the input-token bound.
LIVE_INPUT_OVERHEAD_TOKENS = 256

UsdPerMillion = Annotated[float, Field(gt=0, le=1_000, allow_inf_nan=False)]


class LiveExecutionAuthorization(BaseModel):
    """Human-approved, expiring authorization for one exact provider/model.

    Attributes:
        provider: Catalogued provider this authorization covers.
        model: Catalogued model this authorization covers.
        usd_per_million_input_tokens: Approved input tariff upper bound.
        usd_per_million_output_tokens: Approved output tariff upper bound.
        authorized_by: Accountable human approver identifier.
        authorization_reference: Durable record of the human decision.
        expires_at: Timezone-aware expiry, at most seven days after bootstrap.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, hide_input_in_errors=True,
    )

    provider: LiveProvider
    model: Annotated[str, Field(min_length=1, max_length=128)]
    usd_per_million_input_tokens: UsdPerMillion
    usd_per_million_output_tokens: UsdPerMillion
    authorized_by: Identifier
    authorization_reference: Annotated[str, Field(min_length=8, max_length=256)]
    expires_at: datetime

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Require a catalogued model and a timezone-aware expiry.

        Returns:
            The validated authorization.

        Raises:
            ValueError: If the model is uncatalogued or expiry is naive.
        """
        if self.model not in SUPPORTED_LIVE_MODELS[self.provider]:
            raise ValueError("authorization model is outside the application catalog")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("authorization expiry must be timezone-aware")
        return self

    def worst_case_usd(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Return conservative exposure for the given token upper bounds.

        Args:
            input_tokens: Upper bound on billed input tokens.
            output_tokens: Upper bound on billed output tokens.

        Returns:
            Exact decimal USD exposure; never a billing record.
        """
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * Decimal(str(self.usd_per_million_input_tokens))
            + Decimal(output_tokens) * Decimal(str(self.usd_per_million_output_tokens))
        ) / million


def require_live_execution_authorization(
    authorization: object, *, provider: str, model: str, now: datetime | None = None,
) -> LiveExecutionAuthorization:
    """Admit live dispatch only under a current exact human authorization.

    Args:
        authorization: Value bound at trusted bootstrap, or None.
        provider: Adapter vendor about to be invoked.
        model: Adapter-bound model about to be invoked.
        now: Optional trusted clock for deterministic verification.

    Returns:
        The admitted authorization.

    Raises:
        AuthorityViolationError: If no exact authorization is bound, it covers
            another provider/model, or it has expired.
    """
    if type(authorization) is not LiveExecutionAuthorization:
        raise AuthorityViolationError(
            "Live monetary execution requires an explicit human authorization."
        )
    if authorization.provider != provider or authorization.model != model:
        raise AuthorityViolationError("Live authorization covers a different provider/model.")
    if (datetime.now(UTC) if now is None else now) >= authorization.expires_at:
        raise AuthorityViolationError("Live monetary authorization has expired.")
    return authorization

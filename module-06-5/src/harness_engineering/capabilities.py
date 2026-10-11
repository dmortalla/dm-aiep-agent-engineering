"""Typed capability discovery and selection without execution authority."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from harness_engineering.domain import Identifier
from harness_engineering.errors import ContractValidationError


class CapabilityDefinition(BaseModel):
    """Immutable discovery metadata, never an executable or permission grant.

    Input and output schemas are application-declared Pydantic model classes.
    They must reject undeclared fields. Tags describe functionality only;
    matching them never evaluates permissions or approves an action.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    capability_id: Identifier
    description: str = Field(min_length=1, max_length=2000)
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    tags: tuple[Identifier, ...] = Field(default=(), max_length=32)

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema(cls, schema: type[BaseModel]) -> type[BaseModel]:
        """Require concrete schemas that fail closed on undeclared fields.

        Args:
            schema: Application-declared input or output model class.

        Returns:
            The validated model class.

        Raises:
            ValueError: If the schema accepts undeclared fields or is BaseModel.
        """
        if schema is BaseModel or schema.model_config.get("extra") != "forbid":
            raise ValueError("capability schemas must be concrete models with extra='forbid'")
        return schema

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: tuple[str, ...]) -> tuple[str, ...]:
        """Canonicalize tags and reject ambiguous duplicate metadata.

        Args:
            tags: Declared functionality tags.

        Returns:
            Unique tags in lexical order.

        Raises:
            ValueError: If a tag is declared more than once.
        """
        if len(tags) != len(set(tags)):
            raise ValueError("capability tags must be unique")
        return tuple(sorted(tags))

    @property
    def grants_authority(self) -> bool:
        """Return False; discovery metadata never grants execution authority."""
        return False


class CapabilitySelectionCriteria(BaseModel):
    """Untrusted exact-match discovery criteria, never permission scope.

    Empty identifiers consider all registered capabilities. All required tags
    must match; an empty tag set adds no filter. Matching is case-sensitive.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    capability_ids: tuple[Identifier, ...] = Field(default=(), max_length=100)
    required_tags: tuple[Identifier, ...] = Field(default=(), max_length=32)

    @field_validator("capability_ids", "required_tags")
    @classmethod
    def validate_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Return sorted criteria or reject duplicates.

        Args:
            values: Proposed identifiers or required tags.

        Returns:
            Unique values in lexical order.

        Raises:
            ValueError: If criteria contain duplicate values.
        """
        if len(values) != len(set(values)):
            raise ValueError("selection criteria must be unique")
        return tuple(sorted(values))


class CapabilityRegistry:
    """Application-owned registry containing metadata without tool handlers."""

    def __init__(self) -> None:
        """Initialize an empty registry without external discovery or execution."""
        self._capabilities: dict[str, CapabilityDefinition] = {}

    def register(self, capability: CapabilityDefinition) -> None:
        """Validate and register a capability without replacing existing identity.

        Args:
            capability: Application-declared discovery contract.

        Raises:
            ContractValidationError: If the contract is invalid or identity exists.
        """
        try:
            validated = CapabilityDefinition.model_validate(capability)
        except ValidationError as exc:
            raise ContractValidationError("Invalid capability contract.") from exc
        if validated.capability_id in self._capabilities:
            raise ContractValidationError("Capability identity is already registered.")
        self._capabilities[validated.capability_id] = validated

    def lookup(self, capability_id: str) -> CapabilityDefinition:
        """Return registered metadata for an exact identity.

        Args:
            capability_id: Exact, case-sensitive registered identifier.

        Returns:
            Capability metadata, without permission or execution authority.

        Raises:
            ContractValidationError: If the identity is unknown.
        """
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise ContractValidationError("Unknown capability identity.") from exc

    def list_capabilities(self) -> tuple[CapabilityDefinition, ...]:
        """Return metadata in lexical identity order, independent of registration.

        Returns:
            Immutable snapshot of registered capability metadata.
        """
        return tuple(self._capabilities[key] for key in sorted(self._capabilities))

    def select(
        self, criteria: CapabilitySelectionCriteria
    ) -> tuple[CapabilityDefinition, ...]:
        """Select candidates by declared metadata without authorizing execution.

        Args:
            criteria: Proposed identifiers and required functionality tags.

        Returns:
            Matching metadata in lexical identity order; no matches yields ().

        Raises:
            ContractValidationError: If criteria are invalid or an ID is unknown.
        """
        try:
            validated = CapabilitySelectionCriteria.model_validate(criteria)
        except ValidationError as exc:
            raise ContractValidationError("Invalid capability selection criteria.") from exc
        candidates = (
            tuple(self.lookup(key) for key in validated.capability_ids)
            if validated.capability_ids
            else self.list_capabilities()
        )
        return tuple(
            candidate
            for candidate in candidates
            if set(validated.required_tags).issubset(candidate.tags)
        )

"""Deterministic evidence for REQ-TOOL-001 and REQ-TOOL-002 only."""

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness_engineering.capabilities import (
    CapabilityDefinition,
    CapabilityRegistry,
    CapabilitySelectionCriteria,
)
from harness_engineering.errors import ContractValidationError


class ToolInput(BaseModel):
    """Application-declared example input schema."""

    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=100)


class ToolOutput(BaseModel):
    """Application-declared example output schema."""

    model_config = ConfigDict(extra="forbid", strict=True)
    count: int = Field(ge=0)


def capability(
    identity: str = "search.v1", tags: tuple[str, ...] = ("search",)
) -> CapabilityDefinition:
    """Build inert example capability metadata."""
    return CapabilityDefinition(
        capability_id=identity,
        description="Search declared local data.",
        input_schema=ToolInput,
        output_schema=ToolOutput,
        tags=tags,
    )


def test_identity_and_schema_are_stable_and_frozen() -> None:
    """Preserve caller identity and typed schema references across registration."""
    definition = capability(tags=("search", "local"))
    registry = CapabilityRegistry()
    registry.register(definition)
    found = registry.lookup("search.v1")
    assert found == definition
    assert found.capability_id == "search.v1"
    assert found.input_schema is ToolInput
    assert found.output_schema is ToolOutput
    assert found.tags == ("local", "search")
    assert found.input_schema.model_validate({"query": "example"}).query == "example"
    assert found.output_schema.model_validate({"count": 1}).count == 1
    with pytest.raises(ValidationError, match="frozen"):
        found.capability_id = "changed"


@pytest.mark.parametrize("identity", ["", "../tool", "tool with spaces", "a" * 129])
def test_invalid_identity_is_rejected(identity: str) -> None:
    """Reject malformed or oversized capability identity."""
    with pytest.raises(ValidationError):
        capability(identity)


@pytest.mark.parametrize("schema_field", ["input_schema", "output_schema"])
@pytest.mark.parametrize("schema", [BaseModel, str, lambda: None])
def test_invalid_schema_contract_is_rejected(schema_field: str, schema: object) -> None:
    """Reject generic models, non-model classes, and executable handlers."""
    fields = capability().model_dump()
    fields[schema_field] = schema
    with pytest.raises(ValidationError):
        CapabilityDefinition.model_validate(fields)


def test_schema_must_reject_unknown_fields() -> None:
    """Reject a permissive schema that would silently discard forged fields."""
    class PermissiveInput(BaseModel):
        query: str

    fields = capability().model_dump()
    fields["input_schema"] = PermissiveInput
    with pytest.raises(ValidationError, match="extra='forbid'"):
        CapabilityDefinition.model_validate(fields)


@pytest.mark.parametrize("payload", [{"query": ""}, {"query": 1}, {"query": "x", "approved": True}])
def test_declared_input_schema_rejects_malformed_data(payload: dict[str, object]) -> None:
    """Demonstrate input type, value, and unknown-field validation."""
    with pytest.raises(ValidationError):
        capability().input_schema.model_validate(payload)


def test_declared_output_schema_rejects_malformed_data() -> None:
    """Demonstrate output validation without invoking a tool."""
    with pytest.raises(ValidationError):
        capability().output_schema.model_validate({"count": -1})


def test_duplicate_rejection_preserves_original_contract() -> None:
    """Reject duplicate identity even when its metadata differs."""
    registry = CapabilityRegistry()
    original = capability()
    registry.register(original)
    with pytest.raises(ContractValidationError, match="already registered"):
        registry.register(capability(tags=("other",)))
    assert registry.lookup(original.capability_id) == original


def test_unknown_lookup_fails_closed_with_causal_context() -> None:
    """Reject unknown identities without fabricating capability metadata."""
    with pytest.raises(ContractValidationError, match="Unknown") as error:
        CapabilityRegistry().lookup("unknown")
    assert isinstance(error.value.__cause__, KeyError)


def test_empty_registry_has_no_candidates() -> None:
    """Return empty snapshots and selections when no capabilities are registered."""
    registry = CapabilityRegistry()
    assert registry.list_capabilities() == ()
    assert registry.select(CapabilitySelectionCriteria()) == ()


@pytest.mark.parametrize("reverse", [False, True])
def test_listing_and_selection_order_do_not_depend_on_registration(reverse: bool) -> None:
    """Prove reproducible lexical ordering with reversed registration and criteria."""
    registry = CapabilityRegistry()
    definitions = [capability("z"), capability("a"), capability("m")]
    for definition in reversed(definitions) if reverse else definitions:
        registry.register(definition)
    snapshot = registry.list_capabilities()
    assert tuple(item.capability_id for item in snapshot) == ("a", "m", "z")
    assert registry.select(CapabilitySelectionCriteria()) == snapshot
    selected = registry.select(CapabilitySelectionCriteria(capability_ids=("z", "a")))
    assert tuple(item.capability_id for item in selected) == ("a", "z")
    registry.register(capability("b"))
    assert len(snapshot) == 3


def test_dynamic_selection_matches_all_declared_tags_and_optional_ids() -> None:
    """Change runtime criteria to select functional candidates deterministically."""
    registry = CapabilityRegistry()
    registry.register(capability("local.search", ("local", "search")))
    registry.register(capability("remote.search", ("remote", "search")))
    registry.register(capability("local.count", ("local", "count")))
    selected = registry.select(CapabilitySelectionCriteria(required_tags=("search", "local")))
    assert tuple(item.capability_id for item in selected) == ("local.search",)
    selected = registry.select(CapabilitySelectionCriteria(required_tags=("search",)))
    assert tuple(item.capability_id for item in selected) == ("local.search", "remote.search")
    assert registry.select(CapabilitySelectionCriteria(required_tags=("SEARCH",))) == ()
    assert registry.select(
        CapabilitySelectionCriteria(capability_ids=("local.count",), required_tags=("search",))
    ) == ()


def test_unknown_selection_id_rejects_entire_proposal_before_filtering() -> None:
    """Reject unknown candidates even when tags would exclude them."""
    registry = CapabilityRegistry()
    registry.register(capability())
    with pytest.raises(ContractValidationError, match="Unknown"):
        registry.select(
            CapabilitySelectionCriteria(
                capability_ids=("search.v1", "unknown"), required_tags=("no-match",)
            )
        )


def test_duplicate_metadata_and_criteria_are_rejected() -> None:
    """Prevent duplicates after identifier whitespace normalization."""
    with pytest.raises(ValidationError, match="unique"):
        capability(tags=("search", " search "))
    for field in ("capability_ids", "required_tags"):
        with pytest.raises(ValidationError, match="unique"):
            CapabilitySelectionCriteria.model_validate({field: ["x", " x "]})


def test_unvalidated_instances_cannot_bypass_registry_boundaries() -> None:
    """Revalidate constructed metadata and criteria before registry use."""
    registry = CapabilityRegistry()
    forged = capability().model_copy(update={"capability_id": "../invalid"})
    with pytest.raises(ContractValidationError) as error:
        registry.register(forged)
    assert isinstance(error.value.__cause__, ValidationError)
    assert registry.list_capabilities() == ()
    invalid = CapabilitySelectionCriteria.model_construct(capability_ids=("../invalid",))
    with pytest.raises(ContractValidationError) as error:
        registry.select(invalid)
    assert isinstance(error.value.__cause__, ValidationError)


@pytest.mark.parametrize("field", ["authorized", "approved", "grants_authority", "handler"])
def test_generated_values_cannot_add_execution_authority(field: str) -> None:
    """Reject forged authority fields in both metadata and selection proposals."""
    with pytest.raises(ValidationError):
        CapabilityDefinition.model_validate({**capability().model_dump(), field: True})
    with pytest.raises(ValidationError):
        CapabilitySelectionCriteria.model_validate({field: True})


def test_selection_returns_only_inert_metadata() -> None:
    """Even an authority-looking tag cannot produce approval or invoke a tool."""
    registry = CapabilityRegistry()
    registry.register(capability(tags=("approved",)))
    before = registry.list_capabilities()
    selected = registry.select(CapabilitySelectionCriteria(required_tags=("approved",)))
    assert selected == before
    assert selected[0].grants_authority is False
    assert not hasattr(selected[0], "handler")
    assert not hasattr(selected[0], "execute")
    assert not hasattr(registry, "authorize")
    assert registry.list_capabilities() == before

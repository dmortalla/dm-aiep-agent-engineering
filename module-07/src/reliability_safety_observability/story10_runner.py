"""Story 10 bounded release-artifact orchestration and reviewer handoff.

The runner reuses the accepted producer seams and readiness contracts; it owns
no new authority. Artifacts are derived by ``ReadinessVerifier.artifacts`` from
authenticated producer records and published as one digest-addressed reviewer
manifest in the contract-mandated ignored, runtime-local reviewer storage —
never as new evidence-store records, so the frozen producer-authority contract
(REQ-EVD-001) is untouched. Credentials are never treated as authorization;
ambient live configuration is refused by the producers themselves, and no
provider is executed. Verification reloads and re-derives everything and
performs no writes; open live claims stay open.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .evidence_records import EvidenceError, EvidenceStore, digest, encoded
from .release_readiness import GateExecutor, ReadinessVerifier

_MANIFEST_SCHEMA: Final = 1
_FORBIDDEN_MARKERS: Final[tuple[str, ...]] = ("module7::canary::", '"content"')
_REQUIRED_ARTIFACTS: Final[frozenset[str]] = frozenset((
    "integrated_acceptance",
    "traceability",
    "failure_path",
    "adversarial_security",
    "quality_gate",
    "dependency",
    "claim_audit",
    "live_claim_ledger",
))
_MANIFEST_INPUT_KEYS: Final[frozenset[str]] = frozenset((
    "evaluation",
    "lab",
    "workflow",
    "accepted_tests",
    "audit",
    "gate",
))
_DEFAULT_REVIEWER_DIRNAME: Final = ".review-storage"
_DEFAULT_RETAINED_GENERATIONS: Final = 3
_MAX_RETAINED_GENERATIONS: Final = 32


@dataclass(frozen=True)
class ReleasePublication:
    """One published, digest-addressed reviewer manifest of record.

    Attributes:
        candidate: Immutable candidate digest the artifacts are bound to.
        contract: Approved Story 10 contract digest.
        inputs: Authenticated producer reference per input producer name.
        artifact_digests: Canonical digest per derived artifact name.
        manifest_reference: SHA-256 of the exact published manifest bytes.
        manifest_path: Runtime-local reviewer-storage path of the manifest.
    """

    candidate: str
    contract: str
    inputs: dict[str, str | None]
    artifact_digests: dict[str, str]
    manifest_reference: str
    manifest_path: Path


def _validate_manifest_shape(manifest: dict[str, object]) -> None:
    """Reject malformed manifests with actionable errors, before nested access."""
    required = {
        "schema", "candidate", "contract", "inputs", "gate_reference",
        "artifact_digests", "artifacts",
    }
    if type(manifest) is not dict:
        raise EvidenceError("Release manifest must be a mapping.")
    if set(manifest) != required:
        missing, extra = required - set(manifest), set(manifest) - required
        raise EvidenceError(
            "Release manifest shape is invalid "
            f"(missing: {sorted(missing)}; unexpected: {sorted(extra)})."
        )
    if manifest["schema"] != _MANIFEST_SCHEMA:
        raise EvidenceError("Release manifest schema is unsupported.")
    for scalar in ("candidate", "contract"):
        value = manifest[scalar]
        if (
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise EvidenceError(f"Release manifest {scalar} is malformed.")
    digests = manifest["artifact_digests"]
    if type(digests) is not dict or set(digests) != set(_REQUIRED_ARTIFACTS):
        raise EvidenceError("Release manifest artifact set is invalid.")
    for value in digests.values():
        hexdigits = "0123456789abcdef"
        if type(value) is not str or len(value) != 64 or any(c not in hexdigits for c in value):
            raise EvidenceError("Release manifest artifact digest is malformed.")
    inputs = manifest["inputs"]
    if type(inputs) is not dict or set(inputs) != set(_MANIFEST_INPUT_KEYS):
        raise EvidenceError(
            "Release manifest input set is invalid "
            "(requires evaluation, lab, workflow, accepted_tests, audit, gate)."
        )
    for name, reference in inputs.items():
        if reference is not None and (
            type(reference) is not str
            or len(reference) != 64
            or any(character not in "0123456789abcdef" for character in reference)
        ):
            raise EvidenceError(f"Release manifest {name} reference is malformed.")
    if manifest["gate_reference"] != inputs["gate"]:
        raise EvidenceError("Release manifest gate fields are contradictory.")
    artifacts = manifest["artifacts"]
    if type(artifacts) is not dict or set(artifacts) != set(_REQUIRED_ARTIFACTS):
        raise EvidenceError("Release manifest artifacts container is invalid.")


def prune_release_history(
    runtime: Path,
    *,
    current_candidate: str | None = None,
    retained_generations: int = _DEFAULT_RETAINED_GENERATIONS,
) -> list[str]:
    """Apply the bounded deterministic retention policy; explicit-invocation only.

    Ownership: the application alone owns reviewer-artifact retention. Only
    ``<runtime>/release/<candidate>/manifest.json`` files are considered;
    every candidate directory must be a hex digest whose manifest declares the
    same candidate, so unrelated or foreign content fails closed rather than
    being swept away. The current candidate's manifest is always preserved,
    and the remaining generations kept are the ``retained_generations`` newest
    by candidate digest (deterministic; no wall clock participates). Deletion
    is bounded to the per-candidate ``manifest.json`` file and its own now
    empty directory; nothing outside the dedicated release subtree is touched.

    Args:
        runtime: The dedicated reviewer runtime root.
        current_candidate: Candidate whose evidence must never be deleted.
        retained_generations: How many non-current generations to retain.

    Returns:
        The candidate directories pruned, in deterministic order.

    Raises:
        EvidenceError: If retention bounds are invalid or the release tree
            contains unexpected content.
    """
    if not 1 <= retained_generations <= _MAX_RETAINED_GENERATIONS:
        raise EvidenceError("Retention bound is outside the accepted range.")
    release_dir = (runtime / "release").resolve()
    if not release_dir.is_dir():
        return []
    generations: dict[str, Path] = {}
    for path in sorted(release_dir.glob("*/manifest.json")):
        candidate_dir = path.parent.name
        if not all(c in "0123456789abcdef" for c in candidate_dir) or len(candidate_dir) != 64:
            raise EvidenceError("Release history contains an unexpected directory.")
        document = json.loads(path.read_bytes())
        if (
            type(document) is not dict
            or document.get("schema") != _MANIFEST_SCHEMA
            or document.get("candidate") != candidate_dir
        ):
            raise EvidenceError("Release history manifest contradicts its candidate.")
        if path.parent.parent.resolve() != release_dir:
            raise EvidenceError("Release history escapes the dedicated directory.")
        generations[candidate_dir] = path
    protected = {current_candidate} if current_candidate else set()
    removable = sorted(set(generations) - protected)
    pruned = removable[:-retained_generations] if len(removable) > retained_generations else []
    for candidate_dir in pruned:
        target = generations[candidate_dir].resolve()
        if target.parent.parent != release_dir:
            raise EvidenceError("Retention would escape the dedicated directory.")
        target.unlink()
        parent = target.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    return sorted(pruned)


def _publish_manifest_bytes(destination: Path, content: bytes) -> str:
    """Publish one digest-addressed manifest atomically without replacement.

    The ``link`` syscall makes existence and content indivisible: either the
    digest-addressed name does not exist and the link creates it from the
    fully written temporary, or it exists and the caller compares bytes. No
    concurrent writer can overwrite a manifest between the check and the
    publication.
    """
    reference = digest(content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = destination
    if target.exists():
        if target.is_symlink() or target.is_junction():
            raise EvidenceError("Release manifest destination is unsafe.")
        if target.read_bytes() != content:
            raise EvidenceError("Release manifest collision; identical republication only.")
        return reference
    temporary = target.with_name(
        target.name
        + f".{os.getpid()}.{digest(content + str(target).encode())[:8]}.pending"
    )
    with temporary.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    try:
        # ``link`` fails with FileExistsError when the target appeared
        # concurrently: genuine no-overwrite publication.
        os.link(temporary, target)
    except FileExistsError:
        if target.read_bytes() != content:
            message = "Release manifest collision; identical republication only."
            raise EvidenceError(message) from None
    finally:
        temporary.unlink(missing_ok=True)
    return reference


def _default_reviewer_root(module_root: Path) -> Path:
    """Resolve the dedicated ignored runtime-local reviewer root of record.

    D7: the default is ``.review-storage`` inside the module root, excluded
    from Git candidate identity by the module-level ``.gitignore`` entry
    (verified via the repository's own ``check-ignore``) and therefore never
    enumerated by the candidate binding's
    ``git ls-files --others --exclude-standard``. Unlike ``.pytest_cache``,
    this directory is owned by the application, not pytest, so ordinary test
    runs never delete release evidence.
    """
    return (module_root / _DEFAULT_REVIEWER_DIRNAME).resolve()


def _reviewer_root_excluded_from_candidate(module_root: Path, reviewer_root: Path) -> None:
    """D6: reject caller-supplied reviewer roots inside candidate identity.

    A root is safe only when it is Git-ignored (therefore never enumerated by
    the candidate binding's ``ls-files --others --exclude-standard``) or lies
    outside the module root entirely. Nested-content checks are bounded to the
    immediate root names; no recursive discovery is performed.
    """
    module_root = module_root.resolve(strict=True)
    reviewer_root = reviewer_root.resolve()
    if module_root not in reviewer_root.parents and reviewer_root != module_root:
        return  # Outside the module tree: never part of candidate identity.
    relative = reviewer_root.relative_to(module_root)
    first = relative.parts[0] if relative.parts else ""
    probe = f"{first}/" if first else f"{reviewer_root.name}/"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--verbose", probe],
        cwd=str(module_root), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise EvidenceError(
            "Reviewer storage must be Git-ignored so it can never enter "
            "candidate identity; supplied reviewer root is not ignored."
        )


def execute_release_publication(
    module_root: Path,
    *,
    reviewer_root: Path | None = None,
    gate: str | None = None,
    include_accepted_tests: bool = True,
    include_workflow: bool = True,
    include_audit: bool = True,
) -> ReleasePublication:
    """Orchestrate producers, derive the eight artifacts and publish them.

    Args:
        module_root: Standalone Module 7 project root containing the frozen
            authorities and the accepted source tree.
        reviewer_root: Optional ignored runtime-local reviewer storage root;
            defaults to ``.pytest_cache/story10-release`` inside the module.
        gate: Optional authenticated completed gate-of-record reference held in
            the same runtime store; independently reloaded, never executed.
        include_accepted_tests: Whether to execute the fixed accepted-test
            producer (deterministic, bounded, live-provider-free).
        include_workflow: Whether to execute the console workflow producer.
        include_audit: Whether to execute the source-audit producer.

    Returns:
        The published manifest binding, digests and runtime-local path.

    Raises:
        EvidenceError: If binding, artifact set, gate evidence or publication
            integrity fails closed.
        OSError: If a required storage or process operation is unavailable.
    """
    module_root = module_root.resolve(strict=True)
    runtime = (
        _default_reviewer_root(module_root)
        if reviewer_root is None
        else reviewer_root.resolve()
    )
    _reviewer_root_excluded_from_candidate(module_root, runtime)
    store = EvidenceStore(runtime / "records")
    verifier = ReadinessVerifier(module_root, store)
    binding = verifier.binding()
    candidate, contract = binding.candidate_id, binding.contract_sha256
    evaluation = store.record_evaluation(candidate=candidate, contract=contract)
    lab = store.record_lab(candidate=candidate, contract=contract)
    workflow = (
        store.record_workflow(candidate=candidate, contract=contract)
        if include_workflow
        else None
    )
    accepted_tests = (
        store.record_accepted_tests(candidate=candidate, contract=contract)
        if include_accepted_tests
        else None
    )
    audit = (
        store.record_candidate_audit(candidate=candidate, contract=contract)
        if include_audit
        else None
    )
    if gate is not None:
        # Read-only independent reload of the supplied gate-of-record;
        # the formal sequence itself is never executed here.
        GateExecutor(verifier).verify(gate)
    artifacts = verifier.artifacts(
        evaluation,
        lab,
        gate=gate,
        workflow=workflow,
        accepted_tests=accepted_tests,
        audit=audit,
    )
    if frozenset(artifacts) != _REQUIRED_ARTIFACTS:
        raise EvidenceError("Release publication requires exactly the eight artifacts.")
    artifact_digests = {
        name: digest(encoded(payload)) for name, payload in sorted(artifacts.items())
    }
    inputs: dict[str, str | None] = {
        "evaluation": evaluation,
        "lab": lab,
        "workflow": workflow,
        "accepted_tests": accepted_tests,
        "audit": audit,
        "gate": gate,
    }
    manifest = {
        "schema": _MANIFEST_SCHEMA,
        "candidate": candidate,
        "contract": contract,
        "inputs": inputs,
        "gate_reference": gate,
        "artifact_digests": artifact_digests,
        "artifacts": artifacts,
    }
    content = encoded(manifest)
    if any(marker.encode() in content for marker in _FORBIDDEN_MARKERS):
        raise EvidenceError("Release manifest would bear forbidden content markers.")
    manifest_reference = _publish_manifest_bytes(
        runtime / "release" / candidate / "manifest.json", content
    )
    return ReleasePublication(
        candidate=candidate,
        contract=contract,
        inputs=inputs,
        artifact_digests=artifact_digests,
        manifest_reference=manifest_reference,
        manifest_path=(runtime / "release" / candidate / "manifest.json"),
    )


def verify_release_artifacts(
    module_root: Path,
    manifest_path: Path,
    *,
    store_root: Path | None = None,
) -> dict[str, object]:
    """Reload and independently verify one published release manifest; no writes.

    Args:
        module_root: Standalone Module 7 project root used for fresh binding.
        manifest_path: Runtime-local published manifest to verify.
        store_root: Evidence-store root holding the referenced producer
            records; defaults to the sibling ``records`` directory of the
            manifest's reviewer root.

    Returns:
        The freshly re-derived artifact bundle; identical content proves the
        published manifest remains fresh and authentic.

    Raises:
        EvidenceError: If the manifest is malformed, stale, corrupt,
            mismatched, secret-bearing, or its authenticated producer records
            fail closed.
        OSError: If a required storage or process operation is unavailable.
    """
    module_root = module_root.resolve(strict=True)
    unresolved = manifest_path
    # D5: guard the unresolved path first — resolution follows symlinks, so a
    # pre-resolution check is the only reliable symlink refusal.
    if unresolved.is_symlink() or unresolved.is_junction():
        raise EvidenceError("Release manifest path is unsafe (symlink or junction).")
    try:
        manifest_path = unresolved.resolve(strict=True)
    except FileNotFoundError:
        raise EvidenceError("Release manifest is missing.") from None
    except OSError as error:
        raise EvidenceError("Release manifest path cannot be resolved.") from error
    if manifest_path.is_symlink() or manifest_path.is_junction():
        raise EvidenceError("Release manifest path is unsafe (symlink or junction).")
    if not manifest_path.is_file():
        raise EvidenceError("Release manifest is missing.")
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw)
    except (ValueError, TypeError):
        raise EvidenceError("Release manifest is not valid JSON.") from None
    _validate_manifest_shape(manifest)
    if digest(encoded(manifest)) != digest(raw):
        # ``encoded`` is canonical: byte inequality means a non-canonical or
        # corrupted document, which can never pass the digest-addressed name.
        raise EvidenceError("Release manifest bytes are not canonical.")
    if any(marker.encode() in raw for marker in _FORBIDDEN_MARKERS):
        raise EvidenceError("Release manifest bears forbidden content markers.")
    # D4: refuse a missing store before constructing EvidenceStore, which
    # would otherwise create the directory and an origin key as a side effect.
    resolved_store_root = (
        store_root or manifest_path.parents[2] / "records"
    )
    if not resolved_store_root.is_dir():
        raise EvidenceError("Release manifest evidence store is missing.")
    store = EvidenceStore(resolved_store_root)
    verifier = ReadinessVerifier(module_root, store)
    binding = verifier.binding()
    if (manifest["candidate"], manifest["contract"]) != (
        binding.candidate_id,
        binding.contract_sha256,
    ):
        raise EvidenceError("Release manifest is stale for the current candidate.")
    inputs = manifest["inputs"]
    producers = {
        "evaluation": "evaluation_engine",
        "lab": "failure_lab",
        "workflow": "workflow_observability",
        "accepted_tests": "accepted_test_execution",
        "audit": "candidate_audit",
    }
    for name, reference in inputs.items():
        if name == "gate" or reference is None:
            continue
        store.load(
            reference,
            candidate=binding.candidate_id,
            contract=binding.contract_sha256,
            producer=producers[name],
        )
    gate = inputs["gate"]
    if gate is not None:
        GateExecutor(verifier).verify(gate)
    rederived = verifier.artifacts(
        inputs["evaluation"],
        inputs["lab"],
        gate=gate,
        workflow=inputs["workflow"],
        accepted_tests=inputs["accepted_tests"],
        audit=inputs["audit"],
    )
    if frozenset(rederived) != _REQUIRED_ARTIFACTS:
        raise EvidenceError("Re-derived release bundle is incomplete.")
    for name, payload in rederived.items():
        if digest(encoded(payload)) != manifest["artifact_digests"][name]:
            raise EvidenceError(f"Release artifact {name} contradicts its manifest digest.")
        if encoded(payload) != encoded(manifest["artifacts"][name]):
            raise EvidenceError(f"Release artifact {name} differs from its manifest bytes.")
    return rederived

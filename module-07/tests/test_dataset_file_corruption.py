"""Story 6 durable file-level dataset corruption tests (contract Test 1).

The accepted schema-level attacks are already durable; these tests exercise
the actual file loader (``load_benchmark_dataset``) against temporary
corrupted dataset files covering the accepted corruption family: duplicate
scenario IDs, unknown category, unknown vocabulary, reordered scenarios, NaN,
Infinity, duplicate JSON keys (last-wins content tampering) and tampered
bytes/digest mismatch. All files are temporary; the committed authoritative
dataset file is never modified.
"""

import hashlib
import json
from pathlib import Path

import pytest

from reliability_safety_observability import evaluation_dataset as dataset_module
from reliability_safety_observability.evaluation_dataset import (
    COMMITTED_DATASET_VERSION,
    DATASET_DIGESTS,
    load_benchmark_dataset,
)

_COMMITTED_FILE = (
    Path(dataset_module.__file__).resolve().parent
    / "evaluation_data"
    / f"module7-benchmark-v{COMMITTED_DATASET_VERSION}.json"
)


class _Trav:
    """Minimal Traversable over one temporary file root."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def __truediv__(self, name: str) -> "_Trav":
        return _Trav(self._path / name)

    def read_bytes(self) -> bytes:
        return self._path.read_bytes()


class _FakeResources:
    """Resources root redirected to one temporary directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def files(self, package: object) -> _Trav:
        return _Trav(self._root)


@pytest.fixture()
def dataset_root(monkeypatch, tmp_path: Path):
    """Redirect the file loader's package resources to a temporary root."""
    data_dir = tmp_path / "evaluation_data"
    data_dir.mkdir()
    raw = _COMMITTED_FILE.read_bytes()
    (data_dir / f"module7-benchmark-v{COMMITTED_DATASET_VERSION}.json").write_bytes(raw)
    monkeypatch.setattr(
        dataset_module, "resources", _FakeResources(tmp_path), raising=False
    )
    return data_dir


def _matching_pin(monkeypatch, data_dir: Path) -> None:
    """Pin the loader's digest to the current (corrupted) file's digest."""
    raw = (
        data_dir / f"module7-benchmark-v{COMMITTED_DATASET_VERSION}.json"
    ).read_bytes()
    parsed = json.loads(raw.decode("utf-8-sig"))
    digest = dataset_module.canonical_digest(parsed)
    monkeypatch.setattr(dataset_module, "_pinned_digest", lambda version: digest)


def _write_dataset(data_dir: Path, content: object) -> None:
    path = data_dir / f"module7-benchmark-v{COMMITTED_DATASET_VERSION}.json"
    path.write_text(json.dumps(content), encoding="utf-8")


def _raw_path(data_dir: Path) -> Path:
    return data_dir / f"module7-benchmark-v{COMMITTED_DATASET_VERSION}.json"


def test_pristine_file_still_loads(dataset_root: Path) -> None:
    """The redirected pristine file passes the loader unchanged."""
    dataset = load_benchmark_dataset()
    assert dataset.dataset_id == "module7-benchmark"
    assert len(dataset.scenario_ids) == 12


def test_file_with_nan_is_refused(dataset_root: Path) -> None:
    """A NaN constant in the file is refused at the parse boundary."""
    path = _raw_path(dataset_root)
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace('"dataset_version":1', '"dataset_version":NaN'))
    with pytest.raises(dataset_module.ContractValidationError, match="malformed"):
        load_benchmark_dataset()


def test_file_with_infinity_is_refused(dataset_root: Path) -> None:
    """An Infinity constant in the file is refused at the parse boundary."""
    path = _raw_path(dataset_root)
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace('"dataset_version":1', '"dataset_version":Infinity'))
    with pytest.raises(dataset_module.ContractValidationError, match="malformed"):
        load_benchmark_dataset()


def test_file_with_tampered_bytes_is_refused_by_digest(dataset_root: Path) -> None:
    """Any byte-level content change is refused by the pinned digest."""
    path = _raw_path(dataset_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["scenarios"][0]["title"] = "Tampered title"
    _write_dataset(dataset_root, raw)
    with pytest.raises(
        dataset_module.ContractValidationError, match="digest"
    ):
        load_benchmark_dataset()


def test_file_with_duplicate_json_keys_is_refused_by_digest(
    dataset_root: Path,
) -> None:
    """A duplicate-key file is refused (last-wins changes the dataset id)."""
    path = _raw_path(dataset_root)
    raw_text = path.read_text(encoding="utf-8")
    # Inject a second, differing dataset_id key right after the first.
    corrupted = raw_text.replace(
        '"dataset_id":"module7-benchmark",',
        '"dataset_id":"module7-benchmark","dataset_id":"module7-evil",',
        1,
    )
    path.write_text(corrupted, encoding="utf-8")
    with pytest.raises(
        dataset_module.ContractValidationError, match="refusing dataset"
    ):
        load_benchmark_dataset()


def test_file_with_duplicate_scenario_ids_is_refused(
    monkeypatch, dataset_root: Path
) -> None:
    """A file whose scenarios repeat an identifier is refused structurally."""
    path = _raw_path(dataset_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    first_id = raw["scenarios"][0]["scenario_id"]
    raw["scenarios"][1]["scenario_id"] = first_id
    _write_dataset(dataset_root, raw)
    _matching_pin(monkeypatch, dataset_root)
    with pytest.raises(
        dataset_module.ContractValidationError, match="repeat a scenario identifier"
    ):
        load_benchmark_dataset()


def test_file_with_reordered_scenarios_is_refused(
    monkeypatch, dataset_root: Path
) -> None:
    """A file whose scenarios break canonical ordering is refused."""
    path = _raw_path(dataset_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["scenarios"] = list(reversed(raw["scenarios"]))
    _write_dataset(dataset_root, raw)
    _matching_pin(monkeypatch, dataset_root)
    with pytest.raises(
        dataset_module.ContractValidationError, match="canonical ordering"
    ):
        load_benchmark_dataset()


def test_file_with_unknown_category_is_refused(
    monkeypatch, dataset_root: Path
) -> None:
    """A file whose scenario carries an unknown category is refused."""
    path = _raw_path(dataset_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["scenarios"][0]["category"] = "not_a_committed_category"
    _write_dataset(dataset_root, raw)
    _matching_pin(monkeypatch, dataset_root)
    with pytest.raises(
        dataset_module.ContractValidationError,
        match="violates the committed dataset schema",
    ):
        load_benchmark_dataset()


def test_file_with_unknown_coverage_vocabulary_is_refused(
    monkeypatch, dataset_root: Path
) -> None:
    """A file whose scenario carries an unknown coverage label is refused."""
    path = _raw_path(dataset_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["scenarios"][0]["coverage"] = "not_a_committed_coverage"
    _write_dataset(dataset_root, raw)
    _matching_pin(monkeypatch, dataset_root)
    with pytest.raises(
        dataset_module.ContractValidationError,
        match="violates the committed dataset schema",
    ):
        load_benchmark_dataset()


def test_committed_dataset_file_remains_untouched() -> None:
    """The committed file is byte-identical to its pinned reviewed digest."""
    raw = _COMMITTED_FILE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest != ""  # Sanity: file present and readable.
    dataset = load_benchmark_dataset()
    assert dataset.digest == DATASET_DIGESTS[COMMITTED_DATASET_VERSION]

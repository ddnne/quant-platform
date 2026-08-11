"""Phase 7 knowledge store tests."""

from __future__ import annotations

from pathlib import Path

from knowledge.store import KnowledgeArtifact, KnowledgeStore


def test_knowledge_store_creates_root_if_absent(tmp_path: Path):
    """Store should create root directory if it doesn't exist."""
    non_existent = tmp_path / "non_existent" / "knowledge"
    store = KnowledgeStore(non_existent)
    assert store.root.exists()
    assert store.root.is_dir()


def test_knowledge_store_put_returns_artifact_with_metadata(tmp_path: Path):
    """put() should return KnowledgeArtifact with all required fields."""
    store = KnowledgeStore(tmp_path / "k")
    artifact = store.put(
        artifact_type="ResearchMemo",
        schema_version="1",
        producer_role="quant",
        payload={"note": "test insight"},
    )
    assert artifact.artifact_type == "ResearchMemo"
    assert artifact.schema_version == "1"
    assert artifact.producer_role == "quant"
    assert artifact.payload == {"note": "test insight"}
    assert artifact.created_at is not None
    assert len(artifact.artifact_id) > 0


def test_knowledge_store_content_addressing_deduplicates(tmp_path: Path):
    """Identical payloads should produce the same artifact_id (content-addressed)."""
    store = KnowledgeStore(tmp_path / "k")
    first = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "same"},
    )
    second = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "same"},
    )
    assert first.artifact_id == second.artifact_id
    assert first.created_at == second.created_at


def test_knowledge_store_different_payloads_different_ids(tmp_path: Path):
    """Different payloads should produce different artifact_ids."""
    store = KnowledgeStore(tmp_path / "k")
    first = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "first"},
    )
    second = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "second"},
    )
    assert first.artifact_id != second.artifact_id


def test_knowledge_store_parent_tracking(tmp_path: Path):
    """Store should track parent artifact IDs."""
    store = KnowledgeStore(tmp_path / "k")
    parent = store.put(
        artifact_type="ResearchMemo",
        schema_version="1",
        producer_role="fundamental",
        payload={"note": "parent"},
    )
    child = store.put(
        artifact_type="StrategySpec",
        schema_version="1",
        producer_role="strategist",
        payload={"note": "child"},
        parent_artifact_ids=(parent.artifact_id,),
    )
    assert child.parent_artifact_ids == (parent.artifact_id,)
    assert len(child.parent_artifact_ids) == 1


def test_knowledge_store_data_snapshot_id(tmp_path: Path):
    """Store should associate artifacts with data snapshot IDs."""
    store = KnowledgeStore(tmp_path / "k")
    artifact = store.put(
        artifact_type="PaperResult",
        schema_version="1",
        producer_role="paper_runtime",
        payload={"experiment_id": "exp1"},
        data_snapshot_id="snap_123",
    )
    assert artifact.data_snapshot_id == "snap_123"


def test_knowledge_store_get_returns_none_for_missing(tmp_path: Path):
    """get() should return None for non-existent artifacts."""
    store = KnowledgeStore(tmp_path / "k")
    assert store.get("nonexistent") is None


def test_knowledge_store_get_roundtrip(tmp_path: Path):
    """get() should retrieve the same artifact that was put()."""
    store = KnowledgeStore(tmp_path / "k")
    original = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "roundtrip test"},
    )
    retrieved = store.get(original.artifact_id)
    assert retrieved is not None
    assert retrieved.artifact_id == original.artifact_id
    assert retrieved.artifact_type == original.artifact_type
    assert retrieved.schema_version == original.schema_version
    assert retrieved.producer_role == original.producer_role
    assert retrieved.payload == original.payload


def test_knowledge_store_multiple_artifacts_same_type(tmp_path: Path):
    """Store should handle multiple artifacts of the same type."""
    store = KnowledgeStore(tmp_path / "k")
    artifacts = []
    for i in range(5):
        artifact = store.put(
            artifact_type="Insight",
            schema_version="1",
            producer_role="quant",
            payload={"note": f"insight {i}"},
        )
        artifacts.append(artifact)

    # All should have different IDs
    ids = {a.artifact_id for a in artifacts}
    assert len(ids) == 5

    # All should be retrievable
    for artifact in artifacts:
        retrieved = store.get(artifact.artifact_id)
        assert retrieved is not None
        assert retrieved.payload == artifact.payload


def test_knowledge_store_artifact_id_format(tmp_path: Path):
    """Artifact IDs should follow sha256: prefix format."""
    store = KnowledgeStore(tmp_path / "k")
    artifact = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "format test"},
    )
    assert artifact.artifact_id.startswith("sha256:")
    # sha256: + 64 hex chars
    assert len(artifact.artifact_id) == len("sha256:") + 64


def test_knowledge_store_persistence(tmp_path: Path):
    """Artifacts should persist to filesystem."""
    store_path = tmp_path / "knowledge"
    store = KnowledgeStore(store_path)
    artifact = store.put(
        artifact_type="Insight",
        schema_version="1",
        producer_role="quant",
        payload={"note": "persistence test"},
    )

    # File should exist
    expected_filename = f"{artifact.artifact_id.replace(':', '_')}.json"
    expected_path = store_path / expected_filename
    assert expected_path.exists()

    # New store instance should retrieve the same artifact
    new_store = KnowledgeStore(store_path)
    retrieved = new_store.get(artifact.artifact_id)
    assert retrieved is not None
    assert retrieved.artifact_id == artifact.artifact_id

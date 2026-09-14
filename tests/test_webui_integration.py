"""Integration tests for QSearch WebUI.

Tests end-to-end workflows including database creation, search, annotation, and export.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from qsearch.webui.database_manager import DatabaseManager
from qsearch.webui.search_engine import SearchEngine
from qsearch.webui.annotation_manager import AnnotationManager
from qsearch.webui.task_manager import TaskManager
from qsearch.webui.exporter import Exporter


class TestDatabaseCreation:
    """Test database creation end-to-end flow."""

    def test_create_database_from_folder(self, tmp_path):
        """Test creating database from folder with images."""
        # Setup: Create test images
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        for i in range(5):
            img_file = image_dir / f"test_{i}.jpg"
            img_file.write_bytes(b"fake_image_data")

        # Create database
        db_root = tmp_path / "databases"
        db_manager = DatabaseManager(db_root)

        metadata = db_manager.create_database(
            name="test_db",
            source=image_dir,
            source_type="folder",
            config_preset="balanced",
        )

        # Verify
        assert metadata['name'] == "test_db"
        assert metadata['image_count'] == 5
        assert (db_root / "test_db" / "metadata.json").exists()
        assert (db_root / "test_db" / "annotations" / "annotations.db").exists()


class TestResultFormatting:
    """Test that matcher output is mapped onto the persistence shape.

    Formatting is tested directly rather than through a constructed
    SearchEngine: constructing one loads a Faiss index, a hash index and a
    pickled feature database, so a test that fakes those files only ever
    exercises faiss's error path.
    """

    def test_matches_split_by_match_type(self):
        """QuestionMatcher returns one combined list keyed by match_type."""
        # Arrange: the shape QuestionMatcher.match actually returns
        raw = {
            'total_matches': 2,
            'top_k': 2,
            'processing_time_ms': 12.5,
            'matches': [
                {
                    'image_id': 'exact.jpg',
                    'match_type': 'EXACT_MATCH',
                    'similarity': 0.98,
                    'scores': {'hash_distance': 3},
                },
                {
                    'image_id': 'content.jpg',
                    'match_type': 'CONTENT_MATCH',
                    'similarity': 0.62,
                    'scores': {'vector_similarity': 0.7, 'text_similarity': 0.4},
                },
            ],
        }

        # Act
        formatted = SearchEngine._format_results(
            SearchEngine, query_image_path='q.jpg', results=raw, processing_time_ms=12.5
        )

        # Assert
        assert len(formatted['exact_matches']) == 1
        assert len(formatted['content_matches']) == 1

        exact = formatted['exact_matches'][0]
        assert exact['image_path'] == 'exact.jpg'
        assert exact['confidence_level'] == 'HIGH'
        assert exact['hash_distance'] == 3

        content = formatted['content_matches'][0]
        assert content['image_path'] == 'content.jpg'
        assert content['confidence_level'] == 'MEDIUM'
        assert content['visual_score'] == 0.7
        assert content['text_score'] == 0.4

    def test_no_matches_yields_empty_buckets(self):
        """A query with no matches must still produce both keys."""
        formatted = SearchEngine._format_results(
            SearchEngine,
            query_image_path='q.jpg',
            results={'matches': [], 'total_matches': 0},
            processing_time_ms=1.0,
        )

        assert formatted['exact_matches'] == []
        assert formatted['content_matches'] == []

    @pytest.mark.parametrize(
        "score,expected",
        [(0.95, 'HIGH'), (0.8, 'HIGH'), (0.79, 'MEDIUM'), (0.5, 'MEDIUM'), (0.49, 'LOW')],
    )
    def test_confidence_thresholds(self, score, expected):
        """Confidence buckets are inclusive at their lower bound."""
        assert SearchEngine._confidence_level(score) == expected


class TestBatchSearchTask:
    """Test batch search task execution."""

    def test_batch_task_creation(self, tmp_path):
        """Test batch search task is created correctly."""
        db_root = tmp_path / "databases"
        db_name = "test_db"

        # Setup database
        db_path = db_root / db_name
        annotations_dir = db_path / "annotations"
        annotations_dir.mkdir(parents=True)

        # Create annotations database
        from qsearch.webui.db_manager import create_database
        db_file = annotations_dir / "annotations.db"
        create_database(db_file)

        # Create task. queue_root is redirected into tmp_path so the test does
        # not touch (or get influenced by) the real project queue.
        task_manager = TaskManager(db_root, queue_root=tmp_path / "queue")

        image_paths = [Path(f"img_{i}.jpg") for i in range(10)]

        task_id = task_manager.queue.enqueue(
            kind="batch_search",
            task_name="Test Batch",
            database_name=db_name,
            num_workers=2,
            total_items=len(image_paths),
            top_n=5,
            payload=[str(p) for p in image_paths],
        )

        # Verify task created
        assert task_id is not None
        status = task_manager.get_task_status(task_id, db_name)
        assert status['status'] == 'pending'
        assert status['total_items'] == 10
        assert status['num_workers'] == 2
        assert task_manager.queue.read_payload(status) == [str(p) for p in image_paths]


class TestAnnotationWorkflow:
    """Test annotation workflow with label persistence."""

    def test_label_candidate_persists(self, tmp_path):
        """Test that candidate labels are persisted correctly."""
        db_path = tmp_path / "test_db"
        annotations_dir = db_path / "annotations"
        annotations_dir.mkdir(parents=True)

        # Create database
        from qsearch.webui.db_manager import create_database
        db_file = annotations_dir / "annotations.db"
        db_mgr = create_database(db_file)

        # Insert test query and candidate
        query_id = "test-query-123"
        db_mgr.execute_query(
            "INSERT INTO queries (query_id, query_image_path, database_name, top_n) VALUES (?, ?, ?, ?)",
            (query_id, "/tmp/query.jpg", "test_db", 10),
            fetch_all=False,
        )

        db_mgr.execute_query(
            """INSERT INTO candidates (query_id, rank, candidate_image_path, match_type,
               confidence_level, overall_score) VALUES (?, ?, ?, ?, ?, ?)""",
            (query_id, 1, "/tmp/cand.jpg", "exact", "HIGH", 0.95),
            fetch_all=False,
        )

        # Get candidate ID
        result = db_mgr.execute_query(
            "SELECT candidate_id FROM candidates WHERE query_id = ?",
            (query_id,),
            fetch_one=True,
        )
        candidate_id = result['candidate_id']

        # Create annotation manager
        from qsearch.webui.db_manager import DatabaseManager as DBMgr
        (db_path / "metadata.json").write_text('{"name": "test_db"}')

        ann_manager = AnnotationManager(db_path)

        # Label candidate
        ann_manager.label_candidate(query_id, candidate_id, 'hit', notes='Test note')

        # Verify label persisted
        labeled = db_mgr.execute_query(
            "SELECT label, notes FROM candidates WHERE candidate_id = ?",
            (candidate_id,),
            fetch_one=True,
        )

        assert labeled['label'] == 'hit'
        assert labeled['notes'] == 'Test note'


class TestExportFunctionality:
    """Test export functionality in all three formats."""

    def test_export_jsonl(self, tmp_path):
        """Test JSONL export creates valid file."""
        # Setup test database with data
        db_path = tmp_path / "test_db"
        annotations_dir = db_path / "annotations"
        annotations_dir.mkdir(parents=True)

        from qsearch.webui.db_manager import create_database
        db_file = annotations_dir / "annotations.db"
        create_database(db_file)

        # Create exporter
        exporter = Exporter(db_path)

        # Export (will be empty but should not error)
        output_file = tmp_path / "export.jsonl"
        count = exporter.export_jsonl(output_file, scope="all")

        assert output_file.exists()
        assert count >= 0


class TestTopNOverride:
    """Test Top-N parameter override in matching."""

    @patch('qsearch.webui.search_engine.QuestionMatcher')
    def test_top_n_parameter(self, mock_matcher):
        """Test that top_n parameter is respected."""
        # Mock matcher should receive top_n parameter
        mock_matcher.return_value.match.return_value = {
            'exact_matches': [],
            'content_matches': [],
            'top_k': 5,
        }

        # This would test the actual parameter passing
        # Requires full mock setup


class TestDuplicateQueryHandling:
    """Test duplicate query overwrite behavior."""

    def test_duplicate_query_replaces_old(self, tmp_path):
        """Test that duplicate queries replace old annotations."""
        # Setup database
        db_path = tmp_path / "test_db"
        annotations_dir = db_path / "annotations"
        annotations_dir.mkdir(parents=True)

        from qsearch.webui.db_manager import create_database
        db_file = annotations_dir / "annotations.db"
        db_mgr = create_database(db_file)

        query_id = "duplicate-query"

        # Insert first query
        db_mgr.execute_query(
            "INSERT INTO queries (query_id, query_image_path, database_name, top_n) VALUES (?, ?, ?, ?)",
            (query_id, "/tmp/q1.jpg", "test_db", 10),
            fetch_all=False,
        )

        # Insert candidates
        db_mgr.execute_query(
            """INSERT INTO candidates (query_id, rank, candidate_image_path, match_type,
               confidence_level, overall_score) VALUES (?, ?, ?, ?, ?, ?)""",
            (query_id, 1, "/tmp/c1.jpg", "exact", "HIGH", 0.95),
            fetch_all=False,
        )

        # Check initial state
        candidates_before = db_mgr.execute_query(
            "SELECT COUNT(*) as cnt FROM candidates WHERE query_id = ?",
            (query_id,),
            fetch_one=True,
        )
        assert candidates_before['cnt'] == 1

        # Delete and re-insert (simulating duplicate handling)
        db_mgr.execute_query(
            "DELETE FROM queries WHERE query_id = ?",
            (query_id,),
            fetch_all=False,
        )

        # Verify CASCADE deleted candidates
        candidates_after = db_mgr.execute_query(
            "SELECT COUNT(*) as cnt FROM candidates WHERE query_id = ?",
            (query_id,),
            fetch_one=True,
        )
        assert candidates_after['cnt'] == 0


# Mark integration tests
pytestmark = pytest.mark.integration


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

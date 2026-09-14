"""Database management module for QSearch WebUI.

Handles creation, listing, deletion, and metadata management of question databases.
Each database contains index files and annotation data.
"""

import json
import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml

from qsearch.config.loader import ConfigLoader
from qsearch.webui.db_manager import DatabaseManager, create_database

# database_manager.py -> src/qsearch/webui -> project root is 3 levels up
_DEFAULT_FEATURES_PATH = Path(__file__).resolve().parents[3] / "config" / "features.yaml"

logger = logging.getLogger(__name__)


class DatabaseManagementError(Exception):
    """Base exception for database management errors."""
    pass


class DatabaseManager:
    """Manages question image databases for QSearch WebUI."""

    def __init__(self, databases_root: Path):
        """Initialize database manager.

        Args:
            databases_root: Root directory for all databases (e.g., data/databases/)
        """
        self.databases_root = Path(databases_root)
        self.databases_root.mkdir(parents=True, exist_ok=True)

    def create_database(
        self,
        name: str,
        source: Union[Path, List[Path], str],
        source_type: str = "folder",
        config_preset: Optional[str] = None,
        config_yaml: Optional[str] = None,
    ) -> Dict:
        """Create a new question database.

        Args:
            name: Database name (must be unique, alphanumeric + underscore/hyphen)
            source: Folder path, list of file paths, or ZIP file path
            source_type: Type of source - 'folder', 'file_list', or 'zip'
            config_preset: Deprecated, retained for callers still passing it;
                only recorded in metadata and no longer selects a config
            config_yaml: Configuration YAML for this database. When omitted the
                project defaults in config/features.yaml are used.

        Returns:
            Database metadata dictionary

        Raises:
            DatabaseManagementError: If name is invalid, already exists, or creation fails
        """
        # Validate database name
        self._validate_database_name(name)

        # Check for duplicates
        if self._database_exists(name):
            raise DatabaseManagementError(f"Database '{name}' already exists")

        # Create database directory structure
        db_dir = self.databases_root / name
        db_dir.mkdir(parents=True, exist_ok=True)

        index_dir = db_dir / "index"
        index_dir.mkdir(exist_ok=True)

        annotations_dir = db_dir / "annotations"
        annotations_dir.mkdir(exist_ok=True)

        try:
            # Scan and collect images
            logger.info(f"Scanning images from {source_type}: {source}")
            image_paths = self._scan_images(source, source_type, db_dir)

            if not image_paths:
                raise DatabaseManagementError(f"No valid images found in {source}")

            logger.info(f"Found {len(image_paths)} images")

            # Load or create configuration
            if config_yaml:
                # Explicit per-database config, normally assembled by the
                # create-database form from its feature/index controls.
                config = yaml.safe_load(config_yaml)
                config_source = "custom"
            else:
                # No config supplied (e.g. programmatic callers): fall back to
                # the project defaults so the database is still buildable.
                config = ConfigLoader.load_yaml(_DEFAULT_FEATURES_PATH)
                config_source = "default"

            # Create metadata
            metadata = {
                "name": name,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "image_count": len(image_paths),
                "config_source": config_source,
                "config_preset": config_preset,
                "config_yaml": config_yaml if config_yaml else None,
                "index_built": False,
                "statistics": {
                    "total_queries": 0,
                    "completed_queries": 0,
                    "unlabeled_queries": 0,
                    "total_candidates": 0,
                    "labeled_candidates": 0,
                    "hit_rate": 0.0,
                },
            }

            # Save image list for index building
            image_list_path = db_dir / "image_list.txt"
            with open(image_list_path, 'w', encoding='utf-8') as f:
                for img_path in image_paths:
                    f.write(f"{img_path}\n")

            # Save metadata
            metadata_path = db_dir / "metadata.json"
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Save configuration
            config_path = db_dir / "config.yaml"
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(
                    config, f, default_flow_style=False,
                    allow_unicode=True, sort_keys=False,
                )

            # Initialize annotations database
            annotations_db_path = annotations_dir / "annotations.db"
            create_database(annotations_db_path)

            logger.info(f"Database '{name}' created successfully at {db_dir}")

            return metadata

        except Exception as e:
            # Clean up on failure
            if db_dir.exists():
                shutil.rmtree(db_dir)
            raise DatabaseManagementError(f"Failed to create database: {e}") from e

    def enqueue_index_build(
        self,
        name: str,
        num_workers: Optional[int] = None,
        batch_size: int = 32,
    ) -> str:
        """Queue an index build to run in the scheduler process.

        This is the path the WebUI uses. Building inline would block the
        Streamlit script for the whole run — on a large database that is tens of
        minutes during which the browser shows a spinner and nothing else in the
        app responds.

        Args:
            name: Database name
            num_workers: Parallel worker processes. Clamped to the CPU count.
            batch_size: Text/image feature extraction batch size.

        Returns:
            Task ID, trackable on the task monitor page

        Raises:
            DatabaseManagementError: If database not found or enqueue fails
        """
        db_dir = self.databases_root / name
        if not db_dir.exists():
            raise DatabaseManagementError(f"Database '{name}' not found")

        try:
            from qsearch.webui.task_manager import TaskManager

            task_manager = TaskManager(self.databases_root)
            task_id = task_manager.enqueue_index_build(
                database_name=name,
                num_workers=num_workers,
                batch_size=batch_size,
            )

            logger.info(f"Queued index build for '{name}' as task {task_id[:8]}")
            return task_id

        except Exception as e:
            raise DatabaseManagementError(f"Failed to queue index build: {e}") from e

    def build_index(
        self,
        name: str,
        num_workers: Optional[int] = None,
        batch_size: int = 32,
    ) -> Dict:
        """Build search index synchronously, in the calling process.

        Kept for CLI use. The WebUI should call :meth:`enqueue_index_build`
        instead so the build does not block the Streamlit script.

        Args:
            name: Database name
            num_workers: Parallel worker processes. Clamped to the CPU count.
            batch_size: Text/image feature extraction batch size.

        Returns:
            Index statistics dictionary

        Raises:
            DatabaseManagementError: If database not found or index build fails
        """
        db_dir = self.databases_root / name
        if not db_dir.exists():
            raise DatabaseManagementError(f"Database '{name}' not found")

        try:
            from qsearch.indexing.builder import build_index
            from qsearch.tasks.settings import clamp_workers

            config_path = db_dir / "config.yaml"
            image_list_path = db_dir / "image_list.txt"
            output_dir = db_dir / "index"

            logger.info(f"Building index for database '{name}'...")

            stats = build_index(
                config_path=str(config_path),
                image_list=str(image_list_path),
                output_dir=str(output_dir),
                num_workers=clamp_workers(num_workers),
                batch_size=batch_size,
            )

            self._update_metadata(name, {"index_built": True, "index_stats": stats})

            logger.info(f"Index built successfully for database '{name}'")
            return stats

        except Exception as e:
            raise DatabaseManagementError(f"Failed to build index: {e}") from e

    def list_databases(self) -> List[Dict]:
        """List all databases with metadata.

        Returns:
            List of database metadata dictionaries sorted by creation date (newest first)
        """
        databases = []

        for db_dir in self.databases_root.iterdir():
            if not db_dir.is_dir():
                continue

            metadata_path = db_dir / "metadata.json"
            if not metadata_path.exists():
                logger.warning(f"Skipping directory without metadata: {db_dir}")
                continue

            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # Update statistics from annotations database
                metadata["statistics"] = self._get_statistics(db_dir.name)

                databases.append(metadata)

            except Exception as e:
                logger.error(f"Error reading metadata for {db_dir.name}: {e}")
                continue

        # Sort by created_at (newest first)
        databases.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return databases

    def get_database_info(self, name: str) -> Dict:
        """Get detailed information about a database.

        Args:
            name: Database name

        Returns:
            Database metadata with current statistics

        Raises:
            DatabaseManagementError: If database not found
        """
        db_dir = self.databases_root / name
        metadata_path = db_dir / "metadata.json"

        if not metadata_path.exists():
            raise DatabaseManagementError(f"Database '{name}' not found")

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            # Get current statistics from annotations database
            metadata["statistics"] = self._get_statistics(name)

            # Add index information
            index_dir = db_dir / "index"
            if index_dir.exists():
                index_stats_path = index_dir / "index_stats.json"
                if index_stats_path.exists():
                    with open(index_stats_path, 'r', encoding='utf-8') as f:
                        metadata["index_stats"] = json.load(f)

            return metadata

        except Exception as e:
            raise DatabaseManagementError(f"Failed to get database info: {e}") from e

    def delete_database(self, name: str) -> None:
        """Delete a database and all its data.

        Args:
            name: Database name

        Raises:
            DatabaseManagementError: If database not found or deletion fails
        """
        db_dir = self.databases_root / name

        if not db_dir.exists():
            raise DatabaseManagementError(f"Database '{name}' not found")

        try:
            shutil.rmtree(db_dir)
            logger.info(f"Database '{name}' deleted successfully")

        except Exception as e:
            raise DatabaseManagementError(f"Failed to delete database: {e}") from e

    def _validate_database_name(self, name: str) -> None:
        """Validate database name.

        Args:
            name: Database name to validate

        Raises:
            DatabaseManagementError: If name is invalid
        """
        if not name:
            raise DatabaseManagementError("Database name cannot be empty")

        if len(name) > 100:
            raise DatabaseManagementError("Database name too long (max 100 characters)")

        # Allow alphanumeric, underscore, hyphen
        if not all(c.isalnum() or c in ('_', '-') for c in name):
            raise DatabaseManagementError(
                "Database name can only contain letters, numbers, underscores, and hyphens"
            )

    def _database_exists(self, name: str) -> bool:
        """Check if database already exists.

        Args:
            name: Database name

        Returns:
            True if database exists, False otherwise
        """
        db_dir = self.databases_root / name
        return db_dir.exists() and (db_dir / "metadata.json").exists()

    def _scan_images(
        self,
        source: Union[Path, List[Path], str],
        source_type: str,
        db_dir: Path,
    ) -> List[Path]:
        """Scan and collect image paths from source.

        Args:
            source: Image source (folder, file list, or ZIP)
            source_type: Type of source
            db_dir: Database directory for extraction

        Returns:
            List of valid image paths

        Raises:
            DatabaseManagementError: If source is invalid or no images found
        """
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp'}
        image_paths = []

        if source_type == "folder":
            source_path = Path(source)
            if not source_path.exists() or not source_path.is_dir():
                raise DatabaseManagementError(f"Folder not found: {source}")

            # Single walk with a suffix test, not one rglob per extension.
            #
            # Globbing both "*.jpg" and "*.JPG" double-counts on Windows, where
            # the filesystem is case-insensitive: both patterns match the same
            # file. That inflated image_count and made every index build process
            # each image twice.
            image_paths = [
                path for path in source_path.rglob("*")
                if path.is_file() and path.suffix.lower() in image_extensions
            ]

        elif source_type == "file_list":
            if isinstance(source, (list, tuple)):
                # List of paths provided directly
                for path_str in source:
                    path = Path(path_str)
                    if path.exists() and path.suffix.lower() in image_extensions:
                        image_paths.append(path)
            else:
                # File containing list of paths
                list_path = Path(source)
                if not list_path.exists():
                    raise DatabaseManagementError(f"File list not found: {source}")

                with open(list_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        path = Path(line.strip())
                        if path.exists() and path.suffix.lower() in image_extensions:
                            image_paths.append(path)

        elif source_type == "zip":
            zip_path = Path(source)
            if not zip_path.exists():
                raise DatabaseManagementError(f"ZIP file not found: {source}")

            # Extract ZIP to images directory
            extract_dir = db_dir / "images"
            extract_dir.mkdir(exist_ok=True)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            # Same single-walk approach as the folder branch, for the same
            # case-insensitivity reason.
            image_paths = [
                path for path in extract_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in image_extensions
            ]

        else:
            raise DatabaseManagementError(f"Unknown source type: {source_type}")

        # Resolve, then de-duplicate while preserving order. A file list can
        # legitimately name the same image twice, and duplicates cost a full
        # extraction pass each.
        seen = set()
        unique_paths = []

        for path in image_paths:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique_paths.append(resolved)

        return unique_paths

    def _get_statistics(self, name: str) -> Dict:
        """Get current statistics from annotations database.

        Args:
            name: Database name

        Returns:
            Statistics dictionary
        """
        db_dir = self.databases_root / name
        annotations_db_path = db_dir / "annotations" / "annotations.db"

        if not annotations_db_path.exists():
            return {
                "total_queries": 0,
                "completed_queries": 0,
                "unlabeled_queries": 0,
                "total_candidates": 0,
                "labeled_candidates": 0,
                "hit_rate": 0.0,
            }

        try:
            from qsearch.webui.db_manager import get_database_manager

            db_manager = get_database_manager(annotations_db_path)

            # Query stats_summary view
            result = db_manager.execute_query(
                "SELECT * FROM stats_summary",
                fetch_one=True,
            )

            if result:
                return {
                    "total_queries": result["total_queries"] or 0,
                    "completed_queries": result["completed_queries"] or 0,
                    "unlabeled_queries": result["unlabeled_queries"] or 0,
                    "total_candidates": result["total_candidates"] or 0,
                    "labeled_candidates": result["labeled_candidates"] or 0,
                    "hit_rate": float(result["hit_rate"] or 0.0),
                }

        except Exception as e:
            logger.error(f"Error getting statistics for {name}: {e}")

        return {
            "total_queries": 0,
            "completed_queries": 0,
            "unlabeled_queries": 0,
            "total_candidates": 0,
            "labeled_candidates": 0,
            "hit_rate": 0.0,
        }

    def _update_metadata(self, name: str, updates: Dict) -> None:
        """Update database metadata.

        Args:
            name: Database name
            updates: Dictionary of fields to update
        """
        db_dir = self.databases_root / name
        metadata_path = db_dir / "metadata.json"

        if not metadata_path.exists():
            raise DatabaseManagementError(f"Database '{name}' not found")

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            metadata.update(updates)

            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Error updating metadata for {name}: {e}")

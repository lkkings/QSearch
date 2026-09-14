"""Database manager for QSearch WebUI.

Handles SQLite connection management, schema initialization, and migrations.
Provides connection pooling and retry logic for concurrent access.
"""

import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database connections with pooling and retry logic."""

    def __init__(
        self,
        db_path: Path,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ):
        """Initialize database manager.

        Args:
            db_path: Path to SQLite database file
            timeout: Connection timeout in seconds
            max_retries: Maximum number of retry attempts for locked database
            retry_delay: Delay between retries in seconds
        """
        self.db_path = Path(db_path)
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._connection = None

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema on first connection
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Initialize database schema if not exists."""
        schema_path = Path(__file__).parent / "schema.sql"

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()

        # Create database and apply schema
        with self.get_connection() as conn:
            conn.executescript(schema_sql)
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    @contextmanager
    def get_connection(self, read_only: bool = False):
        """Get a database connection with retry logic.

        Args:
            read_only: If True, open connection in read-only mode

        Yields:
            sqlite3.Connection: Database connection

        Raises:
            sqlite3.OperationalError: If database is locked after all retries
        """
        conn = None
        last_error = None

        for attempt in range(self.max_retries):
            try:
                # Open connection with timeout
                uri = f"file:{self.db_path}"
                if read_only:
                    uri += "?mode=ro"

                conn = sqlite3.connect(
                    uri,
                    timeout=self.timeout,
                    uri=True,
                    check_same_thread=False,
                )

                # Enable foreign keys
                conn.execute("PRAGMA foreign_keys = ON")

                # Set row factory for dict-like access
                conn.row_factory = sqlite3.Row

                # Enable WAL mode for better concurrency
                if not read_only:
                    conn.execute("PRAGMA journal_mode = WAL")

                yield conn
                return

            except sqlite3.OperationalError as e:
                last_error = e
                if "locked" in str(e).lower() and attempt < self.max_retries - 1:
                    logger.warning(
                        f"Database locked, retry {attempt + 1}/{self.max_retries} "
                        f"after {self.retry_delay}s"
                    )
                    time.sleep(self.retry_delay)
                    continue
                else:
                    raise

            finally:
                if conn:
                    conn.close()

        # If we get here, all retries failed
        if last_error:
            raise last_error

    def execute_query(
        self,
        query: str,
        params: Optional[tuple] = None,
        fetch_one: bool = False,
        fetch_all: bool = True,
    ):
        """Execute a SQL query with retry logic.

        Args:
            query: SQL query to execute
            params: Query parameters
            fetch_one: If True, return single row
            fetch_all: If True, return all rows

        Returns:
            Query results or None
        """
        params = params or ()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)

            if fetch_one:
                return cursor.fetchone()
            elif fetch_all:
                return cursor.fetchall()
            else:
                conn.commit()
                return cursor.lastrowid

    def execute_many(self, query: str, params_list: list) -> None:
        """Execute a SQL query with multiple parameter sets.

        Args:
            query: SQL query to execute
            params_list: List of parameter tuples
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()

    def vacuum(self) -> None:
        """Reclaim unused database space."""
        with self.get_connection() as conn:
            conn.execute("VACUUM")
            logger.info("Database vacuumed")

    def get_table_info(self, table_name: str) -> list:
        """Get column information for a table.

        Args:
            table_name: Name of the table

        Returns:
            List of column information dictionaries
        """
        query = f"PRAGMA table_info({table_name})"
        return self.execute_query(query, fetch_all=True)

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database.

        Args:
            table_name: Name of the table

        Returns:
            True if table exists, False otherwise
        """
        query = """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name=?
        """
        result = self.execute_query(query, (table_name,), fetch_one=True)
        return result is not None

    def close(self) -> None:
        """Close database connection if open."""
        if self._connection:
            self._connection.close()
            self._connection = None
            logger.info(f"Database connection closed: {self.db_path}")


def create_database(db_path: Path) -> DatabaseManager:
    """Create and initialize a new database.

    Args:
        db_path: Path where database should be created

    Returns:
        Initialized DatabaseManager instance
    """
    db_manager = DatabaseManager(db_path)
    logger.info(f"Database created successfully at {db_path}")
    return db_manager


def get_database_manager(db_path: Path) -> DatabaseManager:
    """Get a DatabaseManager instance for an existing database.

    Args:
        db_path: Path to existing database

    Returns:
        DatabaseManager instance

    Raises:
        FileNotFoundError: If database file does not exist
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    return DatabaseManager(db_path)

"""
WorkspaceStore: Run-scoped SQLite storage for structured artifacts.

Stores artifacts like:
- CompanySnapshot
- EvidenceCards
- ThreadBriefs
- VerticalDossiers
- VerificationReport
- CrossVerticalMap
- ValuationPack

Each artifact has:
- Unique ID
- Type (for filtering)
- Producer (which agent created it)
- JSON content
- Summary (human-readable)
- Evidence IDs (links to EvidenceStore)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uuid6 import uuid7


def generate_artifact_id(artifact_type: str) -> str:
    """Generate a unique artifact ID with type prefix."""
    return f"{artifact_type}_{uuid7()}"


class WorkspaceStore:
    """SQLite-backed store for run-scoped artifacts.

    Each research run has its own workspace.db file containing all
    structured artifacts produced during the run.

    Thread-safe for single-writer, multiple-reader scenarios.
    """

    def __init__(self, db_path: Path | str) -> None:
        """Initialize WorkspaceStore.

        Args:
            db_path: Path to the workspace.db file.
        """
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._initialized = False

    def init(self) -> None:
        """Initialize the database schema.

        Creates tables if they don't exist. Safe to call multiple times.
        """
        if self._initialized:
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_conn()
        cursor = conn.cursor()

        # Artifacts table - main storage for all structured outputs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                producer TEXT NOT NULL,
                json TEXT NOT NULL,
                summary TEXT,
                evidence_ids TEXT
            )
        """)

        # Index for type-based queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(type)
        """)

        # Index for producer-based queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_artifacts_producer ON artifacts(producer)
        """)

        # Search log table - track all web searches performed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_log (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                provider TEXT NOT NULL,
                created_at TEXT NOT NULL,
                result_json TEXT
            )
        """)

        conn.commit()
        self._initialized = True

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                isolation_level="DEFERRED",
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def put_artifact(
        self,
        artifact_type: str,
        producer: str,
        json_obj: dict[str, Any],
        summary: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> str:
        """Store an artifact.

        Args:
            artifact_type: Type of artifact (e.g., "evidence_card", "vertical_dossier").
            producer: Name of the agent/component that produced this artifact.
            json_obj: The artifact content as a dict.
            summary: Optional human-readable summary.
            evidence_ids: Optional list of evidence IDs this artifact references.

        Returns:
            The generated artifact ID.
        """
        self.init()

        artifact_id = generate_artifact_id(artifact_type)
        created_at = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO artifacts (id, type, created_at, producer, json, summary, evidence_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                artifact_type,
                created_at,
                producer,
                json.dumps(json_obj, default=str),
                summary,
                json.dumps(evidence_ids) if evidence_ids else None,
            ),
        )
        conn.commit()

        return artifact_id

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        """Get an artifact by ID.

        Args:
            artifact_id: The artifact ID.

        Returns:
            Dict with artifact data, or None if not found.
        """
        self.init()

        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM artifacts WHERE id = ?",
            (artifact_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_artifact(row)

    def list_artifacts(self, artifact_type: str | None = None) -> list[dict[str, Any]]:
        """List artifacts, optionally filtered by type.

        Args:
            artifact_type: Optional type to filter by.

        Returns:
            List of artifact dicts.
        """
        self.init()

        conn = self._get_conn()
        cursor = conn.cursor()

        if artifact_type:
            cursor.execute(
                "SELECT * FROM artifacts WHERE type = ? ORDER BY created_at DESC",
                (artifact_type,),
            )
        else:
            cursor.execute(
                "SELECT * FROM artifacts ORDER BY created_at DESC"
            )

        return [self._row_to_artifact(row) for row in cursor.fetchall()]

    def _row_to_artifact(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a database row to an artifact dict."""
        return {
            "id": row["id"],
            "type": row["type"],
            "created_at": row["created_at"],
            "producer": row["producer"],
            "content": json.loads(row["json"]),
            "summary": row["summary"],
            "evidence_ids": json.loads(row["evidence_ids"]) if row["evidence_ids"] else [],
        }

    def log_search(
        self,
        query: str,
        provider: str,
        results: list[dict[str, Any]] | None = None,
    ) -> str:
        """Log a search query and its results.

        Args:
            query: The search query string.
            provider: The search provider used (e.g., "openai_web_search").
            results: Optional list of search results.

        Returns:
            The generated search log ID.
        """
        self.init()

        search_id = f"search_{uuid7()}"
        created_at = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO search_log (id, query, provider, created_at, result_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                search_id,
                query,
                provider,
                created_at,
                json.dumps(results, default=str) if results else None,
            ),
        )
        conn.commit()

        return search_id

    def get_search_log(self) -> list[dict[str, Any]]:
        """Get all search log entries.

        Returns:
            List of search log entries.
        """
        self.init()

        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM search_log ORDER BY created_at DESC")

        return [
            {
                "id": row["id"],
                "query": row["query"],
                "provider": row["provider"],
                "created_at": row["created_at"],
                "results": json.loads(row["result_json"]) if row["result_json"] else None,
            }
            for row in cursor.fetchall()
        ]

    def count_artifacts(self, artifact_type: str | None = None) -> int:
        """Count artifacts, optionally by type.

        Args:
            artifact_type: Optional type to filter by.

        Returns:
            Number of matching artifacts.
        """
        self.init()

        conn = self._get_conn()
        cursor = conn.cursor()

        if artifact_type:
            cursor.execute(
                "SELECT COUNT(*) FROM artifacts WHERE type = ?",
                (artifact_type,),
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM artifacts")

        return cursor.fetchone()[0]

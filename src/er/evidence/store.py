"""
Evidence store for managing research evidence.

The central store for ALL external content. Every piece of data from outside
the system gets stored here with full provenance tracking.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from er.logging import get_logger
from er.types import Evidence, SourceTier, ToSRisk, generate_id, utc_now

logger = get_logger(__name__)


class EvidenceStore:
    """Central store for all evidence with provenance tracking.

    Stores raw content as files under .cache/blobs/{sha256_hash}
    and metadata in SQLite at .cache/evidence.db.
    """

    def __init__(self, cache_dir: str | Path) -> None:
        """Initialize evidence store.

        Args:
            cache_dir: Base directory for cache storage.
        """
        self.cache_dir = Path(cache_dir)
        self.blobs_dir = self.cache_dir / "blobs"
        self.db_path = self.cache_dir / "evidence.db"
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize the store - create directories and database schema."""
        # Create directories
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)

        # Open database connection
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Create schema
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                content_type TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                snippet TEXT NOT NULL,
                title TEXT,
                published_at TEXT,
                author TEXT,
                tos_risk TEXT NOT NULL DEFAULT 'none',
                source_tier TEXT NOT NULL DEFAULT 'other',
                blob_path TEXT
            )
        """)

        # Create indexes for common queries
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_hash ON evidence(content_hash)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_url)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_tier ON evidence(source_tier)"
        )

        await self._db.commit()
        logger.info("Evidence store initialized", cache_dir=str(self.cache_dir))

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    def _get_blob_path(self, content_hash: str) -> Path:
        """Get the path for a blob file based on content hash.

        Uses first 2 chars as subdirectory for better filesystem performance.
        """
        return self.blobs_dir / content_hash[:2] / content_hash

    async def _store_blob(self, content: bytes, content_hash: str) -> str:
        """Store blob content if not already present.

        Returns:
            Relative path to blob from cache_dir.
        """
        blob_path = self._get_blob_path(content_hash)

        if not blob_path.exists():
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            blob_path.write_bytes(content)
            logger.debug("Stored blob", hash=content_hash[:12], size=len(content))

        # Return relative path
        return str(blob_path.relative_to(self.cache_dir))

    async def store(
        self,
        url: str,
        content: bytes,
        content_type: str,
        snippet: str,
        title: str | None = None,
        published_at: datetime | None = None,
        author: str | None = None,
        tos_risk: ToSRisk = ToSRisk.NONE,
        source_tier: SourceTier = SourceTier.OTHER,
    ) -> Evidence:
        """Store evidence with content and metadata.

        Content is hashed with SHA-256. If same hash already exists, reuses blob
        but creates new evidence record (same content can be cited multiple times).

        Args:
            url: Source URL of the content.
            content: Raw content bytes.
            content_type: MIME type of content.
            snippet: Extracted text snippet.
            title: Title of the content.
            published_at: Publication date if known.
            author: Author if known.
            tos_risk: Terms of service risk level.
            source_tier: Source tier classification.

        Returns:
            Evidence record with ID and metadata.
        """
        if not self._db:
            raise RuntimeError("EvidenceStore not initialized. Call init() first.")

        # Compute hash and store blob
        content_hash = hashlib.sha256(content).hexdigest()
        blob_path = await self._store_blob(content, content_hash)

        # Generate evidence ID and timestamp
        evidence_id = generate_id("ev")
        retrieved_at = utc_now()

        # Insert into database
        await self._db.execute(
            """
            INSERT INTO evidence (
                evidence_id, source_url, retrieved_at, content_type, content_hash,
                snippet, title, published_at, author, tos_risk, source_tier, blob_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                url,
                retrieved_at.isoformat(),
                content_type,
                content_hash,
                snippet,
                title,
                published_at.isoformat() if published_at else None,
                author,
                tos_risk.value,
                source_tier.value,
                blob_path,
            ),
        )
        await self._db.commit()

        evidence = Evidence(
            evidence_id=evidence_id,
            source_url=url,
            retrieved_at=retrieved_at,
            content_type=content_type,
            content_hash=content_hash,
            snippet=snippet,
            title=title,
            published_at=published_at,
            author=author,
            tos_risk=tos_risk,
            source_tier=source_tier,
            blob_path=blob_path,
        )

        logger.info(
            "Stored evidence",
            evidence_id=evidence_id,
            url=url[:80],
            tier=source_tier.value,
        )

        return evidence

    async def get(self, evidence_id: str) -> Evidence | None:
        """Retrieve evidence by ID.

        Args:
            evidence_id: The evidence ID to look up.

        Returns:
            Evidence record or None if not found.
        """
        if not self._db:
            raise RuntimeError("EvidenceStore not initialized. Call init() first.")

        async with self._db.execute(
            "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_evidence(row)

    async def get_blob(self, evidence_id: str) -> bytes | None:
        """Retrieve raw blob content for evidence.

        Args:
            evidence_id: The evidence ID.

        Returns:
            Raw bytes content or None if not found.
        """
        evidence = await self.get(evidence_id)
        if not evidence or not evidence.blob_path:
            return None

        blob_path = self.cache_dir / evidence.blob_path
        if not blob_path.exists():
            logger.warning("Blob file missing", evidence_id=evidence_id)
            return None

        return blob_path.read_bytes()

    async def search(self, query: str, limit: int = 20) -> list[Evidence]:
        """Search evidence by text in snippet.

        Simple case-insensitive text search on snippet content.

        Args:
            query: Search query string.
            limit: Maximum results to return.

        Returns:
            List of matching evidence records.
        """
        if not self._db:
            raise RuntimeError("EvidenceStore not initialized. Call init() first.")

        # Simple LIKE search - could be upgraded to FTS5 for larger datasets
        async with self._db.execute(
            """
            SELECT * FROM evidence
            WHERE snippet LIKE ?
            ORDER BY retrieved_at DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_evidence(row) for row in rows]

    async def list_by_source(self, source_pattern: str) -> list[Evidence]:
        """List evidence by source URL pattern.

        Args:
            source_pattern: Pattern to match source URLs (supports SQL LIKE wildcards).

        Returns:
            List of matching evidence records.
        """
        if not self._db:
            raise RuntimeError("EvidenceStore not initialized. Call init() first.")

        async with self._db.execute(
            """
            SELECT * FROM evidence
            WHERE source_url LIKE ?
            ORDER BY retrieved_at DESC
            """,
            (source_pattern,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_evidence(row) for row in rows]

    async def list_by_tier(self, tier: SourceTier) -> list[Evidence]:
        """List evidence by source tier.

        Args:
            tier: Source tier to filter by.

        Returns:
            List of evidence records in that tier.
        """
        if not self._db:
            raise RuntimeError("EvidenceStore not initialized. Call init() first.")

        async with self._db.execute(
            """
            SELECT * FROM evidence
            WHERE source_tier = ?
            ORDER BY retrieved_at DESC
            """,
            (tier.value,),
        ) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_evidence(row) for row in rows]

    async def count(self) -> int:
        """Get total count of evidence records."""
        if not self._db:
            raise RuntimeError("EvidenceStore not initialized. Call init() first.")

        async with self._db.execute("SELECT COUNT(*) FROM evidence") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def stats(self) -> dict[str, Any]:
        """Get statistics about stored evidence.

        Returns:
            Dict with counts by tier, tos_risk, etc.
        """
        if not self._db:
            raise RuntimeError("EvidenceStore not initialized. Call init() first.")

        stats: dict[str, Any] = {}

        # Total count
        stats["total"] = await self.count()

        # Count by tier
        async with self._db.execute(
            "SELECT source_tier, COUNT(*) FROM evidence GROUP BY source_tier"
        ) as cursor:
            rows = await cursor.fetchall()
            stats["by_tier"] = {row[0]: row[1] for row in rows}

        # Count by tos_risk
        async with self._db.execute(
            "SELECT tos_risk, COUNT(*) FROM evidence GROUP BY tos_risk"
        ) as cursor:
            rows = await cursor.fetchall()
            stats["by_tos_risk"] = {row[0]: row[1] for row in rows}

        return stats

    def _row_to_evidence(self, row: aiosqlite.Row) -> Evidence:
        """Convert a database row to Evidence dataclass."""
        return Evidence(
            evidence_id=row["evidence_id"],
            source_url=row["source_url"],
            retrieved_at=datetime.fromisoformat(row["retrieved_at"]),
            content_type=row["content_type"],
            content_hash=row["content_hash"],
            snippet=row["snippet"],
            title=row["title"],
            published_at=(
                datetime.fromisoformat(row["published_at"])
                if row["published_at"]
                else None
            ),
            author=row["author"],
            tos_risk=ToSRisk(row["tos_risk"]),
            source_tier=SourceTier(row["source_tier"]),
            blob_path=row["blob_path"],
        )

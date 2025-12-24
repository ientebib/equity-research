"""
Event store for agent message logging.

Append-only event store that logs every agent message and enables full audit trails.
Uses JSONL for full message storage and SQLite for fast indexed queries.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import orjson

from er.logging import get_logger
from er.types import AgentMessage, MessageType

logger = get_logger(__name__)


class EventStore:
    """Immutable log of all agent interactions.

    Every message gets recorded with:
    - Full JSON in append-only JSONL file
    - Index fields in SQLite for fast queries
    """

    def __init__(self, output_dir: str | Path) -> None:
        """Initialize event store.

        Args:
            output_dir: Directory for run output (output/{run_id}/).
        """
        self.output_dir = Path(output_dir)
        self.jsonl_path: Path | None = None
        self.db_path: Path | None = None
        self._db: aiosqlite.Connection | None = None
        self._run_id: str | None = None

    async def init(self, run_id: str) -> None:
        """Initialize the store for a specific run.

        Creates files and tables.

        Args:
            run_id: The run identifier.
        """
        self._run_id = run_id

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set up file paths
        self.jsonl_path = self.output_dir / "events.jsonl"
        self.db_path = self.output_dir / "events.db"

        # Open database connection
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Create schema
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                message_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                message_type TEXT NOT NULL,
                confidence REAL,
                evidence_count INTEGER,
                jsonl_offset INTEGER
            )
        """)

        # Create indexes
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_from_agent ON events(from_agent)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_to_agent ON events(to_agent)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_type ON events(message_type)"
        )
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_ts ON events(ts)")

        await self._db.commit()

        logger.info("Event store initialized", run_id=run_id, output_dir=str(self.output_dir))

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def append(self, message: AgentMessage) -> None:
        """Append a message to the event log.

        Args:
            message: The agent message to store.
        """
        if not self._db or not self.jsonl_path:
            raise RuntimeError("EventStore not initialized. Call init() first.")

        # Serialize message to JSON
        message_dict = self._message_to_dict(message)
        json_line = orjson.dumps(message_dict).decode("utf-8") + "\n"

        # Get current file offset before writing
        if self.jsonl_path.exists():
            jsonl_offset = self.jsonl_path.stat().st_size
        else:
            jsonl_offset = 0

        # Append to JSONL file
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json_line)

        # Insert index record into SQLite
        await self._db.execute(
            """
            INSERT INTO events (
                message_id, run_id, ts, from_agent, to_agent,
                message_type, confidence, evidence_count, jsonl_offset
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.run_id,
                message.timestamp.isoformat(),
                message.from_agent,
                message.to_agent,
                message.message_type.value,
                message.confidence,
                len(message.evidence_ids),
                jsonl_offset,
            ),
        )
        await self._db.commit()

        logger.debug(
            "Appended event",
            message_id=message.message_id,
            type=message.message_type.value,
            from_agent=message.from_agent,
        )

    async def get(self, message_id: str) -> AgentMessage | None:
        """Retrieve a message by ID.

        Args:
            message_id: The message ID to look up.

        Returns:
            AgentMessage or None if not found.
        """
        if not self._db or not self.jsonl_path:
            raise RuntimeError("EventStore not initialized. Call init() first.")

        # Get offset from SQLite
        async with self._db.execute(
            "SELECT jsonl_offset FROM events WHERE message_id = ?", (message_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        # Read from JSONL at offset
        return await self._read_at_offset(row["jsonl_offset"])

    async def query(
        self,
        from_agent: str | None = None,
        to_agent: str | None = None,
        message_type: MessageType | None = None,
        since: datetime | None = None,
    ) -> list[AgentMessage]:
        """Query messages with filters.

        Args:
            from_agent: Filter by sender agent.
            to_agent: Filter by recipient agent.
            message_type: Filter by message type.
            since: Filter by timestamp (messages after this time).

        Returns:
            List of matching messages.
        """
        if not self._db or not self.jsonl_path:
            raise RuntimeError("EventStore not initialized. Call init() first.")

        # Build query
        conditions = []
        params: list[Any] = []

        if from_agent:
            conditions.append("from_agent = ?")
            params.append(from_agent)

        if to_agent:
            conditions.append("to_agent = ?")
            params.append(to_agent)

        if message_type:
            conditions.append("message_type = ?")
            params.append(message_type.value)

        if since:
            conditions.append("ts > ?")
            params.append(since.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT jsonl_offset FROM events WHERE {where_clause} ORDER BY ts ASC"

        # Execute query
        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        # Read messages from JSONL
        messages = []
        for row in rows:
            msg = await self._read_at_offset(row["jsonl_offset"])
            if msg:
                messages.append(msg)

        return messages

    async def get_conversation(self, agent_name: str) -> list[AgentMessage]:
        """Get all messages to/from an agent.

        Args:
            agent_name: The agent name.

        Returns:
            List of messages involving this agent.
        """
        if not self._db or not self.jsonl_path:
            raise RuntimeError("EventStore not initialized. Call init() first.")

        query = """
            SELECT jsonl_offset FROM events
            WHERE from_agent = ? OR to_agent = ?
            ORDER BY ts ASC
        """

        async with self._db.execute(query, (agent_name, agent_name)) as cursor:
            rows = await cursor.fetchall()

        messages = []
        for row in rows:
            msg = await self._read_at_offset(row["jsonl_offset"])
            if msg:
                messages.append(msg)

        return messages

    async def get_phase_messages(self, phase: str) -> list[AgentMessage]:
        """Get all messages from a specific phase.

        Note: This requires messages to have phase in their context.

        Args:
            phase: The phase name.

        Returns:
            List of messages from this phase.
        """
        # Since phase isn't indexed, we need to read all and filter
        # This could be optimized by adding phase to the index
        all_messages = await self.query()
        return [
            msg for msg in all_messages if msg.context.get("phase") == phase
        ]

    async def count_by_type(self) -> dict[MessageType, int]:
        """Count messages by type.

        Returns:
            Dict mapping MessageType to count.
        """
        if not self._db:
            raise RuntimeError("EventStore not initialized. Call init() first.")

        async with self._db.execute(
            "SELECT message_type, COUNT(*) FROM events GROUP BY message_type"
        ) as cursor:
            rows = await cursor.fetchall()

        result: dict[MessageType, int] = {}
        for row in rows:
            try:
                msg_type = MessageType(row[0])
                result[msg_type] = row[1]
            except ValueError:
                # Skip unknown message types
                pass

        return result

    async def count(self) -> int:
        """Get total count of events."""
        if not self._db:
            raise RuntimeError("EventStore not initialized. Call init() first.")

        async with self._db.execute("SELECT COUNT(*) FROM events") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def _read_at_offset(self, offset: int) -> AgentMessage | None:
        """Read a message from JSONL at a specific byte offset.

        Args:
            offset: Byte offset in the JSONL file.

        Returns:
            AgentMessage or None if read fails.
        """
        if not self.jsonl_path or not self.jsonl_path.exists():
            return None

        try:
            with open(self.jsonl_path, "r", encoding="utf-8") as f:
                f.seek(offset)
                line = f.readline()
                if not line:
                    return None

                data = orjson.loads(line)
                return self._dict_to_message(data)
        except Exception as e:
            logger.warning("Failed to read event at offset", offset=offset, error=str(e))
            return None

    def _message_to_dict(self, message: AgentMessage) -> dict[str, Any]:
        """Convert AgentMessage to dict for JSON serialization."""
        return {
            "message_id": message.message_id,
            "run_id": message.run_id,
            "timestamp": message.timestamp.isoformat(),
            "from_agent": message.from_agent,
            "to_agent": message.to_agent,
            "message_type": message.message_type.value,
            "content": message.content,
            "context": message.context,
            "confidence": message.confidence,
            "evidence_ids": list(message.evidence_ids),
            "usage": message.usage,
        }

    def _dict_to_message(self, data: dict[str, Any]) -> AgentMessage:
        """Convert dict to AgentMessage."""
        return AgentMessage(
            message_id=data["message_id"],
            run_id=data["run_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            message_type=MessageType(data["message_type"]),
            content=data["content"],
            context=data.get("context", {}),
            confidence=data.get("confidence"),
            evidence_ids=tuple(data.get("evidence_ids", [])),
            usage=data.get("usage", {}),
        )

"""
Tests for the event store.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from er.coordinator.event_store import EventStore
from er.types import AgentMessage, MessageType


@pytest.fixture
async def event_store(temp_dir: Path) -> EventStore:
    """Create an initialized event store for testing."""
    store = EventStore(temp_dir / "output" / "test_run")
    await store.init("test_run")
    yield store
    await store.close()


def create_test_message(
    run_id: str = "test_run",
    from_agent: str = "researcher_1",
    to_agent: str = "coordinator",
    message_type: MessageType = MessageType.RESEARCH_COMPLETE,
    content: str = "Test content",
    confidence: float | None = 0.8,
    evidence_ids: tuple[str, ...] = ("ev_123",),
) -> AgentMessage:
    """Create a test message."""
    return AgentMessage.create(
        run_id=run_id,
        from_agent=from_agent,
        to_agent=to_agent,
        message_type=message_type,
        content=content,
        confidence=confidence,
        evidence_ids=evidence_ids,
    )


class TestEventStoreAppendAndGet:
    """Test append and get operations."""

    @pytest.mark.asyncio
    async def test_append_and_get(self, event_store: EventStore) -> None:
        """Test storing and retrieving a message."""
        msg = create_test_message()

        await event_store.append(msg)
        retrieved = await event_store.get(msg.message_id)

        assert retrieved is not None
        assert retrieved.message_id == msg.message_id
        assert retrieved.from_agent == msg.from_agent
        assert retrieved.to_agent == msg.to_agent
        assert retrieved.message_type == msg.message_type
        assert retrieved.content == msg.content
        assert retrieved.confidence == msg.confidence
        assert retrieved.evidence_ids == msg.evidence_ids

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(
        self, event_store: EventStore
    ) -> None:
        """Test that getting nonexistent message returns None."""
        result = await event_store.get("msg_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_append_multiple(self, event_store: EventStore) -> None:
        """Test appending multiple messages."""
        messages = [
            create_test_message(from_agent=f"agent_{i}")
            for i in range(5)
        ]

        for msg in messages:
            await event_store.append(msg)

        count = await event_store.count()
        assert count == 5

        # Verify each can be retrieved
        for msg in messages:
            retrieved = await event_store.get(msg.message_id)
            assert retrieved is not None
            assert retrieved.from_agent == msg.from_agent


class TestEventStoreJSONLFormat:
    """Test JSONL file format."""

    @pytest.mark.asyncio
    async def test_jsonl_file_created(
        self, event_store: EventStore, temp_dir: Path
    ) -> None:
        """Test that JSONL file is created."""
        msg = create_test_message()
        await event_store.append(msg)

        jsonl_path = temp_dir / "output" / "test_run" / "events.jsonl"
        assert jsonl_path.exists()

    @pytest.mark.asyncio
    async def test_jsonl_format_valid(
        self, event_store: EventStore, temp_dir: Path
    ) -> None:
        """Test that JSONL file contains valid JSON lines."""
        import orjson

        messages = [create_test_message(from_agent=f"agent_{i}") for i in range(3)]
        for msg in messages:
            await event_store.append(msg)

        jsonl_path = temp_dir / "output" / "test_run" / "events.jsonl"

        with open(jsonl_path, "r") as f:
            lines = f.readlines()

        assert len(lines) == 3

        for line in lines:
            # Each line should be valid JSON
            data = orjson.loads(line)
            assert "message_id" in data
            assert "from_agent" in data
            assert "message_type" in data


class TestEventStoreSQLiteIndexing:
    """Test SQLite indexing."""

    @pytest.mark.asyncio
    async def test_sqlite_db_created(
        self, event_store: EventStore, temp_dir: Path
    ) -> None:
        """Test that SQLite database is created."""
        db_path = temp_dir / "output" / "test_run" / "events.db"
        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_count_by_type(self, event_store: EventStore) -> None:
        """Test counting messages by type."""
        # Add messages of different types
        await event_store.append(
            create_test_message(message_type=MessageType.RESEARCH_COMPLETE)
        )
        await event_store.append(
            create_test_message(message_type=MessageType.RESEARCH_COMPLETE)
        )
        await event_store.append(
            create_test_message(
                message_type=MessageType.CHALLENGE,
                confidence=None,
                evidence_ids=(),
            )
        )

        counts = await event_store.count_by_type()

        assert counts[MessageType.RESEARCH_COMPLETE] == 2
        assert counts[MessageType.CHALLENGE] == 1


class TestEventStoreQuery:
    """Test query functionality."""

    @pytest.mark.asyncio
    async def test_query_by_from_agent(self, event_store: EventStore) -> None:
        """Test querying by from_agent."""
        await event_store.append(create_test_message(from_agent="agent_a"))
        await event_store.append(create_test_message(from_agent="agent_a"))
        await event_store.append(create_test_message(from_agent="agent_b"))

        results = await event_store.query(from_agent="agent_a")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_by_to_agent(self, event_store: EventStore) -> None:
        """Test querying by to_agent."""
        await event_store.append(create_test_message(to_agent="coordinator"))
        await event_store.append(create_test_message(to_agent="judge"))

        results = await event_store.query(to_agent="coordinator")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_query_by_message_type(self, event_store: EventStore) -> None:
        """Test querying by message type."""
        await event_store.append(
            create_test_message(message_type=MessageType.RESEARCH_COMPLETE)
        )
        await event_store.append(
            create_test_message(
                message_type=MessageType.CHALLENGE,
                confidence=None,
                evidence_ids=(),
            )
        )

        results = await event_store.query(message_type=MessageType.CHALLENGE)
        assert len(results) == 1
        assert results[0].message_type == MessageType.CHALLENGE

    @pytest.mark.asyncio
    async def test_get_conversation(self, event_store: EventStore) -> None:
        """Test getting conversation for an agent."""
        await event_store.append(
            create_test_message(from_agent="agent_a", to_agent="coordinator")
        )
        await event_store.append(
            create_test_message(from_agent="coordinator", to_agent="agent_a")
        )
        await event_store.append(
            create_test_message(from_agent="agent_b", to_agent="coordinator")
        )

        conversation = await event_store.get_conversation("agent_a")
        assert len(conversation) == 2


class TestEventStoreConcurrency:
    """Test concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_appends(self, event_store: EventStore) -> None:
        """Test that concurrent appends are safe."""
        messages = [create_test_message(from_agent=f"agent_{i}") for i in range(10)]

        # Append concurrently
        await asyncio.gather(*[event_store.append(msg) for msg in messages])

        count = await event_store.count()
        assert count == 10

        # Verify all messages are retrievable
        for msg in messages:
            retrieved = await event_store.get(msg.message_id)
            assert retrieved is not None

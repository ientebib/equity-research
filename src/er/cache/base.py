"""
Base classes for caching.

This module will implement:
- CacheProtocol: Abstract interface for cache implementations
- CacheKey: Structured cache key generation
- CacheEntry: Wrapper for cached values with metadata (TTL, created_at)
- BaseCacheBackend: Abstract base class for cache backends

Cache backends will support:
- get/set/delete operations
- TTL-based expiration
- Batch operations for efficiency
- Cache statistics and monitoring
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CacheProtocol(ABC):
    """Abstract interface for cache implementations."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Get a value from the cache."""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set a value in the cache."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a value from the cache."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        ...

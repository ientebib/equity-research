"""
Key-value cache implementation.

This module will implement:
- SQLiteKVCache: Async SQLite-backed key-value cache using aiosqlite
  - JSON serialization for complex values
  - TTL support with automatic cleanup
  - Batch get/set operations
  - Index on keys for fast lookups

- InMemoryKVCache: Simple dict-based cache for testing
  - LRU eviction when size limit reached
  - TTL support

Features:
- Namespace support for cache partitioning
- Compression for large values
- Metrics tracking (hits, misses, size)
"""

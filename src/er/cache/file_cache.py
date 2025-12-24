"""
File-based blob cache for large content.

This module will implement:
- FileCache: File system-based cache for large blobs
  - Content-addressed storage using SHA-256 hashes
  - Automatic deduplication
  - Metadata sidecar files (JSON)
  - Compression support (gzip, zstd)

- BlobReference: Lightweight reference to cached blob
  - Hash, size, content_type, created_at
  - Methods to read/stream content

Features:
- LRU eviction based on total size
- Cleanup of orphaned files
- Atomic writes to prevent corruption
- Support for streaming large files
"""

"""
Evidence management package.

This package handles storage and retrieval of evidence:
- Evidence objects with citations
- Deduplication
- Search and filtering
- Provenance tracking
"""

from er.evidence.store import EvidenceStore

__all__ = ["EvidenceStore"]

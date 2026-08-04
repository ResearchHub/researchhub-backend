"""Public schema primitives for the ResearchHub Tiptap document engine."""

from note.services.document_engine.errors import (
    DocumentSchemaMismatch,
    InvalidDocument,
    InvalidDocumentOperation,
)
from note.services.document_engine.registry import (
    EDITOR_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    SCHEMA_FINGERPRINT,
)

__all__ = [
    "DocumentSchemaMismatch",
    "EDITOR_SCHEMA_VERSION",
    "InvalidDocument",
    "InvalidDocumentOperation",
    "LEGACY_SCHEMA_VERSION",
    "SCHEMA_FINGERPRINT",
]

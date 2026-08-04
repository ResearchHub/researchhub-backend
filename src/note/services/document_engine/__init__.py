"""Pure, lossless document runtime for ResearchHub Tiptap notes."""

from note.services.document_engine.editor import apply_operations
from note.services.document_engine.errors import (
    DocumentSchemaMismatch,
    InvalidDocument,
    InvalidDocumentOperation,
)
from note.services.document_engine.reader import derive_plain_text, read_document
from note.services.document_engine.registry import (
    EDITOR_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    SCHEMA_FINGERPRINT,
)
from note.services.document_engine.validator import (
    validate_schema_version,
    validate_stored_document,
)


class NoteDocumentEngine:
    """Stateless facade for validation, bounded reads, and atomic edits."""

    schema_version = EDITOR_SCHEMA_VERSION
    schema_fingerprint = SCHEMA_FINGERPRINT

    def validate(self, payload: object) -> dict:
        request = _request(payload, required={"doc"}, optional={"schema_version"})
        validate_schema_version(request.get("schema_version"))
        doc, changed, warnings = validate_stored_document(request["doc"])
        return _result(
            doc=doc,
            plain_text=derive_plain_text(doc),
            changed=changed,
            warnings=warnings,
            valid=True,
        )

    def read(self, payload: object) -> dict:
        request = _request(
            payload,
            required={"doc"},
            optional={"schema_version", "from", "limit"},
        )
        validate_schema_version(request.get("schema_version"))
        doc, changed, warnings = validate_stored_document(request["doc"])
        response = read_document(
            doc, start=request.get("from", 0), limit=request.get("limit", 100)
        )
        return {
            "schema_version": EDITOR_SCHEMA_VERSION,
            "schema_fingerprint": SCHEMA_FINGERPRINT,
            "changed": changed,
            "warnings": warnings,
            **response,
        }

    def apply(self, payload: object) -> dict:
        request = _request(
            payload,
            required={"doc", "operations"},
            optional={"schema_version"},
        )
        validate_schema_version(request.get("schema_version"))
        base_doc, normalization_changed, base_warnings = validate_stored_document(
            request["doc"]
        )
        result_doc, operation_results, edit_warnings = apply_operations(
            base_doc, request["operations"]
        )
        return _result(
            doc=result_doc,
            plain_text=derive_plain_text(result_doc),
            changed=result_doc != request["doc"],
            normalization_changed=normalization_changed,
            warnings=_deduplicate_warnings([*base_warnings, *edit_warnings]),
            operation_results=operation_results,
        )


def _request(payload: object, *, required: set[str], optional: set[str]) -> dict:
    if not isinstance(payload, dict):
        raise InvalidDocumentOperation("Engine input must be an object", path="request")
    if any(not isinstance(key, str) for key in payload):
        raise InvalidDocumentOperation(
            "Engine input field names must be strings", path="request"
        )
    missing = required - set(payload)
    extra = set(payload) - required - optional
    if missing:
        raise InvalidDocumentOperation(
            f"Engine input is missing fields: {sorted(missing)}", path="request"
        )
    if extra:
        raise InvalidDocumentOperation(
            f"Engine input has unsupported fields: {sorted(extra)}", path="request"
        )
    return payload


def _result(*, doc: dict, plain_text: str, changed: bool, warnings: list, **extra):
    return {
        "schema_version": EDITOR_SCHEMA_VERSION,
        "schema_fingerprint": SCHEMA_FINGERPRINT,
        "doc": doc,
        "plain_text": plain_text,
        "changed": changed,
        "warnings": warnings,
        **extra,
    }


def _deduplicate_warnings(warnings: list[dict]) -> list[dict]:
    deduplicated = []
    seen = set()
    for warning in warnings:
        key = tuple(sorted((key, repr(value)) for key, value in warning.items()))
        if key not in seen:
            seen.add(key)
            deduplicated.append(warning)
    return deduplicated


__all__ = [
    "DocumentSchemaMismatch",
    "EDITOR_SCHEMA_VERSION",
    "InvalidDocument",
    "InvalidDocumentOperation",
    "LEGACY_SCHEMA_VERSION",
    "NoteDocumentEngine",
    "SCHEMA_FINGERPRINT",
]

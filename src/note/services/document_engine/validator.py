"""Public validation entry points for ProseMirror JSON documents."""

from note.services.document_engine.created_validator import CreatedNodeValidator
from note.services.document_engine.errors import (
    DocumentSchemaMismatch,
    InvalidDocument,
)
from note.services.document_engine.grammar import DocumentGrammarValidator
from note.services.document_engine.inspector import DocumentInspector
from note.services.document_engine.normalizer import DocumentNormalizer
from note.services.document_engine.registry import (
    EDITOR_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
)


class SchemaVersionValidator:
    """Resolve the persisted schema sentinel and reject unsupported versions."""

    def validate(self, schema_version: str | None) -> str:
        effective = (
            LEGACY_SCHEMA_VERSION
            if schema_version is None or schema_version == ""
            else schema_version
        )
        if not isinstance(effective, str) or effective not in {
            EDITOR_SCHEMA_VERSION,
            LEGACY_SCHEMA_VERSION,
        }:
            raise DocumentSchemaMismatch(
                f"Unsupported document schema version: {effective!r}",
                path="schema_version",
            )
        return effective


class StoredDocumentValidator:
    """Coordinate structural validation, inspection, and durable normalization."""

    def __init__(
        self,
        grammar: DocumentGrammarValidator | None = None,
        inspector: DocumentInspector | None = None,
        normalizer: DocumentNormalizer | None = None,
    ):
        self.grammar = grammar or DocumentGrammarValidator(InvalidDocument)
        self.inspector = inspector or DocumentInspector()
        self.normalizer = normalizer or DocumentNormalizer()

    def validate(self, doc: object) -> tuple[dict, bool, list[dict]]:
        self.grammar.validate(doc, path="doc")
        if not isinstance(doc, dict) or doc.get("type") != "doc":
            raise InvalidDocument("Document root must have type 'doc'", path="doc.type")
        if "content" not in doc:
            raise InvalidDocument(
                "Document root must contain a content array", path="doc"
            )

        normalized, id_warnings = self.normalizer.normalize(doc)
        warnings = self.inspector.inspect(normalized)
        warnings.extend(id_warnings)
        self.grammar.validate_serialized_size(normalized)
        return normalized, normalized != doc, warnings


def validate_schema_version(schema_version: str | None) -> str:
    """Return the effective supported version or raise for future/unknown input."""

    return SchemaVersionValidator().validate(schema_version)


def validate_stored_document(doc: object) -> tuple[dict, bool, list[dict]]:
    """Validate generic ProseMirror structure and normalize durable node IDs."""

    return StoredDocumentValidator().validate(doc)


def validate_created_node(
    node: object,
    *,
    top_level: bool = True,
    path: str = "node",
) -> dict:
    """Validate and canonicalize one model-created node."""

    return CreatedNodeValidator().validate(node, top_level=top_level, path=path)


def normalize_created_ids(doc: dict) -> tuple[dict, list[dict]]:
    """Assign deterministic IDs to all ID-capable nodes in a created result."""

    return DocumentNormalizer().normalize(doc)

"""Typed failures raised by the note document engine."""


class DocumentEngineError(ValueError):
    """Base error carrying a stable, model-correctable error code."""

    code = "document_engine_error"

    def __init__(self, message: str, *, path: str | None = None):
        super().__init__(message)
        self.path = path

    def as_dict(self) -> dict:
        error = {"code": self.code, "message": str(self)}
        if self.path is not None:
            error["path"] = self.path
        return error


class DocumentSchemaMismatch(DocumentEngineError):  # noqa: N818 - public contract
    """The caller supplied a schema version this engine cannot read."""

    code = "document_schema_mismatch"


class InvalidDocument(DocumentEngineError):  # noqa: N818 - public contract
    """Stored JSON is not a structurally valid ProseMirror document."""

    code = "invalid_document"


class InvalidDocumentOperation(DocumentEngineError):  # noqa: N818 - public contract
    """An edit request is malformed or violates the creation contract."""

    code = "invalid_document_operation"

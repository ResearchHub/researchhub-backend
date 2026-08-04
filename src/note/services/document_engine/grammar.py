"""Generic structural validation for ProseMirror JSON trees."""

import json

from note.services.document_engine.errors import DocumentEngineError
from note.services.document_engine.registry import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_DEPTH,
    MAX_DOCUMENT_NODES,
    MAX_STRING_LENGTH,
)

_NODE_KEYS = frozenset({"type", "attrs", "content", "text", "marks"})
_MARK_KEYS = frozenset({"type", "attrs"})


class DocumentGrammarValidator:
    """Validate bounded JSON structure shared by stored and created content."""

    def __init__(self, error_type: type[DocumentEngineError]):
        self.error_type = error_type
        self.node_count = 0

    def validate(self, node: object, *, path: str):
        """Validate serialized size and recursively validate one node tree."""

        self.node_count = 0
        self.validate_serialized_size(node)
        self._validate_node(node, path=path, depth=0)

    def validate_serialized_size(self, value: object):
        """Reject non-JSON values and documents larger than the configured limit."""

        try:
            encoded = json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (RecursionError, TypeError, ValueError) as exc:
            raise self.error_type(
                "Document must contain only JSON-serializable values", path="doc"
            ) from exc
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise self.error_type(
                f"Document exceeds maximum size of {MAX_DOCUMENT_BYTES} bytes",
                path="doc",
            )

    def _validate_node(self, node: object, *, path: str, depth: int):
        self._record_node(path=path, depth=depth)
        node = self._validate_node_object(node, path=path)
        node_type = self._validate_node_type(node, path=path)
        self._validate_node_attrs(node, path=path, depth=depth)
        content = self._validate_node_content(node, path=path)
        self._validate_node_marks(node, path=path, depth=depth)
        self._validate_text_field(node, node_type=node_type, content=content, path=path)
        self._validate_node_children(content, path=path, depth=depth)

    def _record_node(self, *, path: str, depth: int):
        if depth > MAX_DOCUMENT_DEPTH:
            self._fail(f"Document exceeds maximum depth of {MAX_DOCUMENT_DEPTH}", path)
        self.node_count += 1
        if self.node_count > MAX_DOCUMENT_NODES:
            self._fail(
                f"Document exceeds maximum node count of {MAX_DOCUMENT_NODES}", path
            )

    def _validate_node_object(self, node: object, *, path: str) -> dict:
        if not isinstance(node, dict):
            self._fail("Every node must be an object", path)
        if any(not isinstance(key, str) for key in node):
            self._fail("Node object keys must be strings", path)
        extra_keys = set(node) - _NODE_KEYS
        if extra_keys:
            self._fail(f"Node contains unsupported keys: {sorted(extra_keys)}", path)
        return node

    def _validate_node_type(self, node: dict, *, path: str) -> str:
        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            self._fail("Every node must have a non-empty string type", f"{path}.type")
        if len(node_type) > MAX_STRING_LENGTH:
            self._fail("Node type exceeds the maximum string length", f"{path}.type")
        return node_type

    def _validate_node_attrs(self, node: dict, *, path: str, depth: int):
        attrs = node.get("attrs")
        if "attrs" in node and not isinstance(attrs, dict):
            self._fail("Node attrs must be an object", f"{path}.attrs")
        if isinstance(attrs, dict):
            self._validate_json_value(attrs, path=f"{path}.attrs", depth=depth + 1)

    def _validate_node_content(self, node: dict, *, path: str) -> list | None:
        content = node.get("content")
        if "content" in node and not isinstance(content, list):
            self._fail("Node content must be an array", f"{path}.content")
        return content

    def _validate_node_marks(self, node: dict, *, path: str, depth: int):
        if "marks" not in node:
            return
        marks = node.get("marks")
        if not isinstance(marks, list):
            self._fail("Node marks must be an array", f"{path}.marks")
        for index, mark in enumerate(marks):
            self._validate_mark(mark, path=f"{path}.marks[{index}]", depth=depth)

    def _validate_text_field(
        self,
        node: dict,
        *,
        node_type: str,
        content: list | None,
        path: str,
    ):
        if node_type == "text":
            self._validate_text_leaf(node, content=content, path=path)
        elif "text" in node:
            self._fail("Only text nodes may have a text field", f"{path}.text")

    def _validate_text_leaf(self, node: dict, *, content: list | None, path: str):
        text = node.get("text")
        if not isinstance(text, str) or not text:
            self._fail("Text leaves must contain a non-empty string", f"{path}.text")
        if len(text) > MAX_STRING_LENGTH:
            self._fail("Text leaf exceeds the maximum string length", f"{path}.text")
        if content is not None:
            self._fail("Text leaves cannot contain child nodes", f"{path}.content")

    def _validate_node_children(self, content: list | None, *, path: str, depth: int):
        if content is None:
            return
        for index, child in enumerate(content):
            self._validate_node(child, path=f"{path}.content[{index}]", depth=depth + 1)

    def _validate_mark(self, mark: object, *, path: str, depth: int):
        if not isinstance(mark, dict):
            self._fail("Every mark must be an object", path)
        if any(not isinstance(key, str) for key in mark):
            self._fail("Mark object keys must be strings", path)
        extra_keys = set(mark) - _MARK_KEYS
        if extra_keys:
            self._fail(f"Mark contains unsupported keys: {sorted(extra_keys)}", path)
        mark_type = mark.get("type")
        if not isinstance(mark_type, str) or not mark_type:
            self._fail("Every mark must have a non-empty string type", f"{path}.type")
        if len(mark_type) > MAX_STRING_LENGTH:
            self._fail("Mark type exceeds the maximum string length", f"{path}.type")
        attrs = mark.get("attrs")
        if "attrs" in mark and not isinstance(attrs, dict):
            self._fail("Mark attrs must be an object", f"{path}.attrs")
        if isinstance(attrs, dict):
            self._validate_json_value(attrs, path=f"{path}.attrs", depth=depth + 1)

    def _validate_json_value(self, value: object, *, path: str, depth: int):
        if depth > MAX_DOCUMENT_DEPTH:
            self._fail(f"Document exceeds maximum depth of {MAX_DOCUMENT_DEPTH}", path)
        if isinstance(value, str):
            if len(value) > MAX_STRING_LENGTH:
                self._fail("Attribute exceeds the maximum string length", path)
            return
        if isinstance(value, dict):
            self._validate_json_object(value, path=path, depth=depth)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                self._validate_json_value(
                    child, path=f"{path}[{index}]", depth=depth + 1
                )
            return
        if value is None or isinstance(value, (bool, int, float)):
            return
        self._fail("Attributes must contain only JSON values", path)

    def _validate_json_object(self, value: dict, *, path: str, depth: int):
        for key, child in value.items():
            if not isinstance(key, str):
                self._fail("Attribute object keys must be strings", path)
            if len(key) > MAX_STRING_LENGTH:
                self._fail("Attribute key exceeds the maximum string length", path)
            self._validate_json_value(child, path=f"{path}.{key}", depth=depth + 1)

    def _fail(self, message: str, path: str):
        raise self.error_type(message, path=path)

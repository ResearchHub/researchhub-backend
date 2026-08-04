"""Structural and creation validation for ProseMirror JSON documents."""

import copy
import json
import re
import uuid
from collections.abc import Iterable
from urllib.parse import ParseResult, urlparse

from note.services.document_engine.errors import (
    DocumentEngineError,
    DocumentSchemaMismatch,
    InvalidDocument,
    InvalidDocumentOperation,
)
from note.services.document_engine.registry import (
    CREATABLE_MARKS,
    CREATABLE_NODES,
    CREATABLE_TOP_LEVEL_NODES,
    EDITOR_SCHEMA_VERSION,
    ID_CAPABLE_NODES,
    IMAGE_FIXED_ATTRIBUTES,
    INVENTORY_MARKS,
    INVENTORY_NODES,
    LEGACY_SCHEMA_VERSION,
    LINK_ALLOWED_SCHEMES,
    LINK_FIXED_ATTRIBUTES,
    MAX_CREATED_LANGUAGE_LENGTH,
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_DEPTH,
    MAX_DOCUMENT_NODES,
    MAX_STRING_LENGTH,
)

_NODE_KEYS = frozenset({"type", "attrs", "content", "text", "marks"})
_MARK_KEYS = frozenset({"type", "attrs"})
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID_NAMESPACE = uuid.UUID("b1ab26a0-b48b-5cba-9618-d9675d455b95")
_INLINE_NODES = frozenset({"text", "hardBreak"})
_ITEM_BLOCKS = CREATABLE_TOP_LEVEL_NODES


def validate_schema_version(schema_version: str | None) -> str:
    """Return the effective supported version or raise for future/unknown input."""

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


def validate_stored_document(doc: object) -> tuple[dict, bool, list[dict]]:
    """Validate generic ProseMirror structure and normalize durable node IDs."""

    _guard_serialized_size(doc, InvalidDocument)
    state = _GrammarState(InvalidDocument)
    state.validate_node(doc, path="doc", depth=0)
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise InvalidDocument("Document root must have type 'doc'", path="doc.type")
    if "content" not in doc:
        raise InvalidDocument("Document root must contain a content array", path="doc")

    normalized = copy.deepcopy(doc)
    warnings = _inventory_warnings(normalized)
    id_warnings = _normalize_ids(normalized)
    warnings.extend(id_warnings)
    return normalized, normalized != doc, warnings


def validate_created_node(
    node: object,
    *,
    top_level: bool = True,
    path: str = "node",
) -> dict:
    """Validate and canonicalize one model-created node."""

    _guard_serialized_size(node, InvalidDocumentOperation)
    state = _GrammarState(InvalidDocumentOperation)
    state.validate_node(node, path=path, depth=0)
    assert isinstance(node, dict)  # Narrowed by the grammar validator.
    return _canonicalize_created_node(node, top_level=top_level, path=path)


def normalize_created_ids(doc: dict) -> tuple[dict, list[dict]]:
    """Assign deterministic IDs to all ID-capable nodes in a created result."""

    normalized = copy.deepcopy(doc)
    warnings = _normalize_ids(normalized)
    return normalized, warnings


class _GrammarState:
    def __init__(self, error_type: type[DocumentEngineError]):
        self.error_type = error_type
        self.node_count = 0

    def fail(self, message: str, path: str):
        raise self.error_type(message, path=path)

    def validate_node(self, node: object, *, path: str, depth: int):
        self._record_node(path=path, depth=depth)
        node = self._validate_node_object(node, path=path)
        node_type = self._validate_node_type(node, path=path)
        self._validate_node_attrs(node, path=path, depth=depth)
        content = self._validate_node_content(node, path=path)
        self._validate_node_marks(node, path=path)
        self._validate_text_field(node, node_type=node_type, content=content, path=path)
        self._validate_node_children(content, path=path, depth=depth)

    def _record_node(self, *, path: str, depth: int):
        if depth > MAX_DOCUMENT_DEPTH:
            self.fail(f"Document exceeds maximum depth of {MAX_DOCUMENT_DEPTH}", path)
        self.node_count += 1
        if self.node_count > MAX_DOCUMENT_NODES:
            self.fail(
                f"Document exceeds maximum node count of {MAX_DOCUMENT_NODES}", path
            )

    def _validate_node_object(self, node: object, *, path: str) -> dict:
        if not isinstance(node, dict):
            self.fail("Every node must be an object", path)
        if any(not isinstance(key, str) for key in node):
            self.fail("Node object keys must be strings", path)
        extra_keys = set(node) - _NODE_KEYS
        if extra_keys:
            self.fail(f"Node contains unsupported keys: {sorted(extra_keys)}", path)
        return node

    def _validate_node_type(self, node: dict, *, path: str) -> str:
        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            self.fail("Every node must have a non-empty string type", f"{path}.type")
        if len(node_type) > MAX_STRING_LENGTH:
            self.fail("Node type exceeds the maximum string length", f"{path}.type")
        return node_type

    def _validate_node_attrs(self, node: dict, *, path: str, depth: int):
        attrs = node.get("attrs")
        if "attrs" in node and not isinstance(attrs, dict):
            self.fail("Node attrs must be an object", f"{path}.attrs")
        if isinstance(attrs, dict):
            self.validate_json_value(attrs, path=f"{path}.attrs", depth=depth + 1)

    def _validate_node_content(self, node: dict, *, path: str) -> list | None:
        content = node.get("content")
        if "content" in node and not isinstance(content, list):
            self.fail("Node content must be an array", f"{path}.content")
        return content

    def _validate_node_marks(self, node: dict, *, path: str):
        if "marks" not in node:
            return
        marks = node.get("marks")
        if not isinstance(marks, list):
            self.fail("Node marks must be an array", f"{path}.marks")
        for index, mark in enumerate(marks):
            self.validate_mark(mark, path=f"{path}.marks[{index}]")

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
            self.fail("Only text nodes may have a text field", f"{path}.text")

    def _validate_text_leaf(self, node: dict, *, content: list | None, path: str):
        text = node.get("text")
        if not isinstance(text, str) or not text:
            self.fail("Text leaves must contain a non-empty string", f"{path}.text")
        if len(text) > MAX_STRING_LENGTH:
            self.fail("Text leaf exceeds the maximum string length", f"{path}.text")
        if content is not None:
            self.fail("Text leaves cannot contain child nodes", f"{path}.content")

    def _validate_node_children(self, content: list | None, *, path: str, depth: int):
        if content is None:
            return
        for index, child in enumerate(content):
            self.validate_node(child, path=f"{path}.content[{index}]", depth=depth + 1)

    def validate_mark(self, mark: object, *, path: str):
        if not isinstance(mark, dict):
            self.fail("Every mark must be an object", path)
        if any(not isinstance(key, str) for key in mark):
            self.fail("Mark object keys must be strings", path)
        extra_keys = set(mark) - _MARK_KEYS
        if extra_keys:
            self.fail(f"Mark contains unsupported keys: {sorted(extra_keys)}", path)
        mark_type = mark.get("type")
        if not isinstance(mark_type, str) or not mark_type:
            self.fail("Every mark must have a non-empty string type", f"{path}.type")
        if len(mark_type) > MAX_STRING_LENGTH:
            self.fail("Mark type exceeds the maximum string length", f"{path}.type")
        attrs = mark.get("attrs")
        if "attrs" in mark and not isinstance(attrs, dict):
            self.fail("Mark attrs must be an object", f"{path}.attrs")
        if isinstance(attrs, dict):
            self.validate_json_value(attrs, path=f"{path}.attrs", depth=1)

    def validate_json_value(self, value: object, *, path: str, depth: int):
        if depth > MAX_DOCUMENT_DEPTH:
            self.fail(f"Document exceeds maximum depth of {MAX_DOCUMENT_DEPTH}", path)
        if isinstance(value, str):
            if len(value) > MAX_STRING_LENGTH:
                self.fail("Attribute exceeds the maximum string length", path)
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    self.fail("Attribute object keys must be strings", path)
                if len(key) > MAX_STRING_LENGTH:
                    self.fail("Attribute key exceeds the maximum string length", path)
                self.validate_json_value(child, path=f"{path}.{key}", depth=depth + 1)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                self.validate_json_value(
                    child, path=f"{path}[{index}]", depth=depth + 1
                )
            return
        if value is None or isinstance(value, (bool, int, float)):
            return
        self.fail("Attributes must contain only JSON values", path)


def _guard_serialized_size(value: object, error_type: type[DocumentEngineError]):
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise error_type(
            "Document must contain only JSON-serializable values", path="doc"
        ) from exc
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise error_type(
            f"Document exceeds maximum size of {MAX_DOCUMENT_BYTES} bytes", path="doc"
        )


def _inventory_warnings(doc: dict) -> list[dict]:
    warnings: list[dict] = []
    warned: set[tuple[str, str]] = set()
    for node, path in _walk_nodes(doc):
        node_type = node["type"]
        if node_type not in INVENTORY_NODES:
            _append_type_warning(
                warnings,
                warned,
                code="unknown_node_type",
                type_name=node_type,
                path=path,
                message=(
                    f"Node type {node_type!r} is unknown and was preserved verbatim"
                ),
            )
        elif node_type != "doc" and node_type not in CREATABLE_NODES:
            _append_type_warning(
                warnings,
                warned,
                code="opaque_node_type",
                type_name=node_type,
                path=path,
                message=f"Node type {node_type!r} is opaque and was preserved verbatim",
            )
        _append_projection_warning(warnings, node, path)
        for mark_index, mark in enumerate(node.get("marks", [])):
            mark_type = mark["type"]
            if mark_type not in INVENTORY_MARKS:
                _append_type_warning(
                    warnings,
                    warned,
                    code="unknown_mark_type",
                    type_name=mark_type,
                    path=f"{path}.marks[{mark_index}]",
                    message=(
                        f"Mark type {mark_type!r} is unknown and was preserved verbatim"
                    ),
                )
    return warnings


def _append_projection_warning(warnings: list[dict], node: dict, path: str):
    projected_attribute = {
        "imageBlock": "alt",
        "emoji": "name",
        "youtube": "src",
    }.get(node["type"])
    if projected_attribute is None:
        return
    value = node.get("attrs", {}).get(projected_attribute)
    if value is None and node["type"] == "imageBlock":
        return
    if not isinstance(value, str):
        warnings.append(
            {
                "code": "unprojectable_attribute",
                "node_type": node["type"],
                "path": f"{path}.attrs.{projected_attribute}",
                "message": (
                    f"Attribute {projected_attribute!r} could not be projected as text"
                ),
            }
        )


def _append_type_warning(
    warnings: list[dict],
    warned: set[tuple[str, str]],
    *,
    code: str,
    type_name: str,
    path: str,
    message: str,
):
    key = (code, type_name)
    if key in warned:
        return
    warned.add(key)
    warnings.append(
        {"code": code, "node_type": type_name, "path": path, "message": message}
    )


def _normalize_ids(doc: dict) -> list[dict]:
    seen: set[str] = set()
    warnings: list[dict] = []
    for node, path in _walk_nodes(doc):
        if node["type"] not in ID_CAPABLE_NODES:
            continue
        attrs = node.setdefault("attrs", {})
        current_id = attrs.get("id")
        reason = None
        if not isinstance(current_id, str) or not current_id.strip():
            reason = "missing_node_id"
        elif current_id in seen:
            reason = "duplicate_node_id"
        if reason is None:
            seen.add(current_id)
            continue

        new_id = _deterministic_id(node, path, seen)
        attrs["id"] = new_id
        seen.add(new_id)
        warnings.append(
            {
                "code": reason,
                "node_type": node["type"],
                "path": f"{path}.attrs.id",
                "message": f"Assigned durable ID {new_id!r}",
            }
        )
    return warnings


def _deterministic_id(node: dict, path: str, seen: set[str]) -> str:
    basis = copy.deepcopy(node)
    basis.setdefault("attrs", {}).pop("id", None)
    canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"))
    attempt = 0
    while True:
        candidate = str(uuid.uuid5(_ID_NAMESPACE, f"{path}:{canonical}:{attempt}"))
        if candidate not in seen:
            return candidate
        attempt += 1


def _walk_nodes(node: dict, path: str = "doc") -> Iterable[tuple[dict, str]]:
    yield node, path
    for index, child in enumerate(node.get("content", [])):
        yield from _walk_nodes(child, f"{path}.content[{index}]")


def _canonicalize_created_node(node: dict, *, top_level: bool, path: str) -> dict:
    node_type = node["type"]
    if node_type not in CREATABLE_NODES:
        raise InvalidDocumentOperation(
            f"Node type {node_type!r} is preservation-only", path=f"{path}.type"
        )
    if top_level and node_type not in CREATABLE_TOP_LEVEL_NODES:
        raise InvalidDocumentOperation(
            f"Node type {node_type!r} cannot be a top-level block",
            path=f"{path}.type",
        )

    canonical = {"type": node_type}
    children = node.get("content", [])

    if node_type == "text":
        canonical["text"] = node["text"]
        marks = _canonicalize_marks(node.get("marks", []), path=path)
        if marks:
            canonical["marks"] = marks
        _require_no_attrs(node, path)
        return canonical

    if "marks" in node:
        raise InvalidDocumentOperation(
            "Only text leaves may carry marks in created content", path=f"{path}.marks"
        )

    if node_type in {"paragraph", "heading"}:
        if any(child["type"] not in _INLINE_NODES for child in children):
            raise InvalidDocumentOperation(
                f"{node_type} may contain only text and hardBreak nodes",
                path=f"{path}.content",
            )
        canonical["content"] = [
            _canonicalize_created_node(
                child, top_level=False, path=f"{path}.content[{index}]"
            )
            for index, child in enumerate(children)
        ]
        if node_type == "paragraph":
            _require_no_attrs(node, path)
        else:
            attrs = _require_attr_keys(
                node, required={"level"}, optional=set(), path=path
            )
            level = attrs["level"]
            if (
                isinstance(level, bool)
                or not isinstance(level, int)
                or not 1 <= level <= 6
            ):
                raise InvalidDocumentOperation(
                    "Heading level must be an integer from 1 through 6",
                    path=f"{path}.attrs.level",
                )
            canonical["attrs"] = {"level": level}
        return canonical

    if node_type in {"bulletList", "orderedList", "taskList"}:
        expected = "taskItem" if node_type == "taskList" else "listItem"
        if not children or any(child["type"] != expected for child in children):
            raise InvalidDocumentOperation(
                f"{node_type} must contain one or more {expected} nodes",
                path=f"{path}.content",
            )
        canonical["content"] = [
            _canonicalize_created_node(
                child, top_level=False, path=f"{path}.content[{index}]"
            )
            for index, child in enumerate(children)
        ]
        if node_type == "orderedList":
            attrs = _require_attr_keys(
                node, required=set(), optional={"start"}, path=path
            )
            start = attrs.get("start", 1)
            if isinstance(start, bool) or not isinstance(start, int) or start < 1:
                raise InvalidDocumentOperation(
                    "Ordered-list start must be a positive integer",
                    path=f"{path}.attrs.start",
                )
            canonical["attrs"] = {"start": start}
        else:
            _require_no_attrs(node, path)
        return canonical

    if node_type in {"listItem", "taskItem"}:
        if not children or children[0]["type"] != "paragraph":
            raise InvalidDocumentOperation(
                f"{node_type} must begin with a paragraph", path=f"{path}.content"
            )
        if any(child["type"] not in _ITEM_BLOCKS for child in children[1:]):
            raise InvalidDocumentOperation(
                f"{node_type} contains an invalid block", path=f"{path}.content"
            )
        canonical["content"] = [
            _canonicalize_created_node(
                child, top_level=False, path=f"{path}.content[{index}]"
            )
            for index, child in enumerate(children)
        ]
        if node_type == "taskItem":
            attrs = _require_attr_keys(
                node, required={"checked"}, optional=set(), path=path
            )
            if not isinstance(attrs["checked"], bool):
                raise InvalidDocumentOperation(
                    "Task-item checked must be a boolean",
                    path=f"{path}.attrs.checked",
                )
            canonical["attrs"] = {"checked": attrs["checked"]}
        else:
            _require_no_attrs(node, path)
        return canonical

    if node_type == "codeBlock":
        if any(child["type"] != "text" or child.get("marks") for child in children):
            raise InvalidDocumentOperation(
                "Code blocks may contain only unmarked text leaves",
                path=f"{path}.content",
            )
        attrs = _require_attr_keys(
            node, required=set(), optional={"language"}, path=path
        )
        language = attrs.get("language")
        if language is not None and (
            not isinstance(language, str)
            or not language.strip()
            or len(language) > MAX_CREATED_LANGUAGE_LENGTH
        ):
            raise InvalidDocumentOperation(
                "Code-block language must be null or a short non-empty string",
                path=f"{path}.attrs.language",
            )
        canonical["attrs"] = {"language": language}
        canonical["content"] = [
            _canonicalize_created_node(
                child, top_level=False, path=f"{path}.content[{index}]"
            )
            for index, child in enumerate(children)
        ]
        return canonical

    if node_type in {"horizontalRule", "hardBreak"}:
        _require_leaf(node, path)
        _require_no_attrs(node, path)
        return canonical

    if node_type == "imageBlock":
        _require_leaf(node, path)
        attrs = _require_attr_keys(node, required={"src"}, optional={"alt"}, path=path)
        src = attrs["src"]
        parsed = _parse_url(src)
        if (
            parsed is None
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise InvalidDocumentOperation(
                "Image src must be an absolute HTTPS URL", path=f"{path}.attrs.src"
            )
        alt = attrs.get("alt")
        if alt is not None and (not isinstance(alt, str) or "\x00" in alt):
            raise InvalidDocumentOperation(
                "Image alt must be plain text or null", path=f"{path}.attrs.alt"
            )
        canonical["attrs"] = {
            "src": src,
            **IMAGE_FIXED_ATTRIBUTES,
            "alt": alt,
        }
        return canonical

    raise AssertionError(f"Unhandled creatable node type: {node_type}")


def _canonicalize_marks(marks: list[dict], *, path: str) -> list[dict]:
    canonical: list[dict] = []
    seen: set[str] = set()
    for index, mark in enumerate(marks):
        mark_path = f"{path}.marks[{index}]"
        mark_type = mark["type"]
        if mark_type not in CREATABLE_MARKS:
            raise InvalidDocumentOperation(
                f"Mark type {mark_type!r} is preservation-only",
                path=f"{mark_path}.type",
            )
        if mark_type in seen:
            raise InvalidDocumentOperation(
                f"Duplicate mark type {mark_type!r}", path=mark_path
            )
        seen.add(mark_type)
        result = {"type": mark_type}
        if mark_type == "link":
            attrs = _require_attr_keys(
                mark, required={"href"}, optional=set(), path=mark_path
            )
            href = attrs["href"]
            parsed = _parse_url(href)
            if parsed is None or parsed.scheme not in LINK_ALLOWED_SCHEMES:
                raise InvalidDocumentOperation(
                    "Link href must use http, https, mailto, or tel",
                    path=f"{mark_path}.attrs.href",
                )
            if parsed.scheme in {"http", "https"} and not parsed.netloc:
                raise InvalidDocumentOperation(
                    "HTTP links must be absolute", path=f"{mark_path}.attrs.href"
                )
            result["attrs"] = {"href": href, **LINK_FIXED_ATTRIBUTES}
        elif mark_type == "highlight":
            attrs = _require_attr_keys(
                mark, required=set(), optional={"color"}, path=mark_path
            )
            color = attrs.get("color")
            if color is not None and (
                not isinstance(color, str) or _HEX_COLOR.fullmatch(color) is None
            ):
                raise InvalidDocumentOperation(
                    "Highlight color must be null or a six-digit hex color",
                    path=f"{mark_path}.attrs.color",
                )
            result["attrs"] = {"color": color.lower() if color else None}
        else:
            _require_no_attrs(mark, mark_path)
        canonical.append(result)

    if "code" in seen and len(seen) > 1:
        raise InvalidDocumentOperation(
            "Code marks cannot be combined with other marks", path=f"{path}.marks"
        )
    if {"subscript", "superscript"}.issubset(seen):
        raise InvalidDocumentOperation(
            "Text cannot be both subscript and superscript", path=f"{path}.marks"
        )
    return canonical


def _parse_url(value: object) -> ParseResult | None:
    if not isinstance(value, str):
        return None
    try:
        return urlparse(value)
    except ValueError:
        return None


def _require_leaf(node: dict, path: str):
    if node.get("content"):
        raise InvalidDocumentOperation(
            f"{node['type']} must not contain child nodes", path=f"{path}.content"
        )


def _require_no_attrs(value: dict, path: str):
    if value.get("attrs"):
        raise InvalidDocumentOperation(
            "Attributes are not allowed here", path=f"{path}.attrs"
        )


def _require_attr_keys(
    value: dict,
    *,
    required: set[str],
    optional: set[str],
    path: str,
) -> dict:
    attrs = value.get("attrs", {})
    missing = required - set(attrs)
    extra = set(attrs) - required - optional
    if missing:
        raise InvalidDocumentOperation(
            f"Missing required attributes: {sorted(missing)}", path=f"{path}.attrs"
        )
    if extra:
        raise InvalidDocumentOperation(
            f"Unsupported attributes: {sorted(extra)}", path=f"{path}.attrs"
        )
    return attrs

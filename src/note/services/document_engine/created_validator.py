"""Strict validation and canonicalization for model-created editor nodes."""

import re
from urllib.parse import ParseResult, urlparse

from note.services.document_engine.errors import InvalidDocumentOperation
from note.services.document_engine.grammar import DocumentGrammarValidator
from note.services.document_engine.registry import (
    CREATABLE_MARKS,
    CREATABLE_NODES,
    CREATABLE_TOP_LEVEL_NODES,
    IMAGE_FIXED_ATTRIBUTES,
    LINK_ALLOWED_SCHEMES,
    LINK_FIXED_ATTRIBUTES,
    MAX_CREATED_LANGUAGE_LENGTH,
)

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_INLINE_NODES = frozenset({"text", "hardBreak"})
_ITEM_BLOCKS = CREATABLE_TOP_LEVEL_NODES


class CreatedNodeValidator:
    """Enforce the model-creation allowlist and return canonical editor JSON."""

    _NODE_HANDLERS = {
        "text": "_canonicalize_text",
        "paragraph": "_canonicalize_text_block",
        "heading": "_canonicalize_text_block",
        "bulletList": "_canonicalize_list",
        "orderedList": "_canonicalize_list",
        "taskList": "_canonicalize_list",
        "listItem": "_canonicalize_list_item",
        "taskItem": "_canonicalize_list_item",
        "codeBlock": "_canonicalize_code_block",
        "horizontalRule": "_canonicalize_leaf",
        "hardBreak": "_canonicalize_leaf",
        "imageBlock": "_canonicalize_image",
    }

    def __init__(self, grammar: DocumentGrammarValidator | None = None):
        self.grammar = grammar or DocumentGrammarValidator(InvalidDocumentOperation)

    def validate(
        self,
        node: object,
        *,
        top_level: bool = True,
        path: str = "node",
    ) -> dict:
        self.grammar.validate(node, path=path)
        assert isinstance(node, dict)  # Narrowed by the grammar validator.
        return self._canonicalize_node(node, top_level=top_level, path=path)

    def _canonicalize_node(self, node: dict, *, top_level: bool, path: str) -> dict:
        node_type = node["type"]
        self._validate_creatable_type(node_type, top_level=top_level, path=path)
        if node_type != "text" and "marks" in node:
            raise InvalidDocumentOperation(
                "Only text leaves may carry marks in created content",
                path=f"{path}.marks",
            )

        handler_name = self._NODE_HANDLERS[node_type]
        handler = getattr(self, handler_name)
        return handler(node, path=path)

    def _validate_creatable_type(self, node_type: str, *, top_level: bool, path: str):
        if node_type not in CREATABLE_NODES:
            raise InvalidDocumentOperation(
                f"Node type {node_type!r} is preservation-only", path=f"{path}.type"
            )
        if top_level and node_type not in CREATABLE_TOP_LEVEL_NODES:
            raise InvalidDocumentOperation(
                f"Node type {node_type!r} cannot be a top-level block",
                path=f"{path}.type",
            )

    def _canonicalize_text(self, node: dict, *, path: str) -> dict:
        canonical = {"type": "text", "text": node["text"]}
        marks = self._canonicalize_marks(node.get("marks", []), path=path)
        if marks:
            canonical["marks"] = marks
        self._require_no_attrs(node, path)
        return canonical

    def _canonicalize_text_block(self, node: dict, *, path: str) -> dict:
        node_type = node["type"]
        children = node.get("content", [])
        if any(child["type"] not in _INLINE_NODES for child in children):
            raise InvalidDocumentOperation(
                f"{node_type} may contain only text and hardBreak nodes",
                path=f"{path}.content",
            )

        canonical = {
            "type": node_type,
            "content": self._canonicalize_children(children, path=path),
        }
        if node_type == "paragraph":
            self._require_no_attrs(node, path)
        else:
            canonical["attrs"] = self._canonicalize_heading_attrs(node, path=path)
        return canonical

    def _canonicalize_heading_attrs(self, node: dict, *, path: str) -> dict:
        attrs = self._require_attr_keys(
            node, required={"level"}, optional=set(), path=path
        )
        level = attrs["level"]
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 6:
            raise InvalidDocumentOperation(
                "Heading level must be an integer from 1 through 6",
                path=f"{path}.attrs.level",
            )
        return {"level": level}

    def _canonicalize_list(self, node: dict, *, path: str) -> dict:
        node_type = node["type"]
        children = node.get("content", [])
        expected = "taskItem" if node_type == "taskList" else "listItem"
        if not children or any(child["type"] != expected for child in children):
            raise InvalidDocumentOperation(
                f"{node_type} must contain one or more {expected} nodes",
                path=f"{path}.content",
            )

        canonical = {
            "type": node_type,
            "content": self._canonicalize_children(children, path=path),
        }
        if node_type == "orderedList":
            canonical["attrs"] = self._canonicalize_ordered_list_attrs(node, path=path)
        else:
            self._require_no_attrs(node, path)
        return canonical

    def _canonicalize_ordered_list_attrs(self, node: dict, *, path: str) -> dict:
        attrs = self._require_attr_keys(
            node, required=set(), optional={"start"}, path=path
        )
        start = attrs.get("start", 1)
        if isinstance(start, bool) or not isinstance(start, int) or start < 1:
            raise InvalidDocumentOperation(
                "Ordered-list start must be a positive integer",
                path=f"{path}.attrs.start",
            )
        return {"start": start}

    def _canonicalize_list_item(self, node: dict, *, path: str) -> dict:
        node_type = node["type"]
        children = node.get("content", [])
        if not children or children[0]["type"] != "paragraph":
            raise InvalidDocumentOperation(
                f"{node_type} must begin with a paragraph", path=f"{path}.content"
            )
        if any(child["type"] not in _ITEM_BLOCKS for child in children[1:]):
            raise InvalidDocumentOperation(
                f"{node_type} contains an invalid block", path=f"{path}.content"
            )

        canonical = {
            "type": node_type,
            "content": self._canonicalize_children(children, path=path),
        }
        if node_type == "taskItem":
            canonical["attrs"] = self._canonicalize_task_item_attrs(node, path=path)
        else:
            self._require_no_attrs(node, path)
        return canonical

    def _canonicalize_task_item_attrs(self, node: dict, *, path: str) -> dict:
        attrs = self._require_attr_keys(
            node, required={"checked"}, optional=set(), path=path
        )
        if not isinstance(attrs["checked"], bool):
            raise InvalidDocumentOperation(
                "Task-item checked must be a boolean",
                path=f"{path}.attrs.checked",
            )
        return {"checked": attrs["checked"]}

    def _canonicalize_code_block(self, node: dict, *, path: str) -> dict:
        children = node.get("content", [])
        if any(child["type"] != "text" or child.get("marks") for child in children):
            raise InvalidDocumentOperation(
                "Code blocks may contain only unmarked text leaves",
                path=f"{path}.content",
            )
        attrs = self._require_attr_keys(
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
        return {
            "type": "codeBlock",
            "attrs": {"language": language},
            "content": self._canonicalize_children(children, path=path),
        }

    def _canonicalize_leaf(self, node: dict, *, path: str) -> dict:
        self._require_leaf(node, path)
        self._require_no_attrs(node, path)
        return {"type": node["type"]}

    def _canonicalize_image(self, node: dict, *, path: str) -> dict:
        self._require_leaf(node, path)
        attrs = self._require_attr_keys(
            node, required={"src"}, optional={"alt"}, path=path
        )
        src = attrs["src"]
        parsed = self._parse_url(src)
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
        return {
            "type": "imageBlock",
            "attrs": {"src": src, **IMAGE_FIXED_ATTRIBUTES, "alt": alt},
        }

    def _canonicalize_children(self, children: list[dict], *, path: str) -> list[dict]:
        return [
            self._canonicalize_node(
                child, top_level=False, path=f"{path}.content[{index}]"
            )
            for index, child in enumerate(children)
        ]

    def _canonicalize_marks(self, marks: list[dict], *, path: str) -> list[dict]:
        canonical: list[dict] = []
        seen: set[str] = set()
        for index, mark in enumerate(marks):
            mark_path = f"{path}.marks[{index}]"
            mark_type = mark["type"]
            self._validate_mark_type(mark_type, seen=seen, path=mark_path)
            canonical.append(self._canonicalize_mark(mark, path=mark_path))
            seen.add(mark_type)

        self._validate_mark_combinations(seen, path=path)
        return canonical

    def _validate_mark_type(self, mark_type: str, *, seen: set[str], path: str):
        if mark_type not in CREATABLE_MARKS:
            raise InvalidDocumentOperation(
                f"Mark type {mark_type!r} is preservation-only", path=f"{path}.type"
            )
        if mark_type in seen:
            raise InvalidDocumentOperation(
                f"Duplicate mark type {mark_type!r}", path=path
            )

    def _canonicalize_mark(self, mark: dict, *, path: str) -> dict:
        mark_type = mark["type"]
        if mark_type == "link":
            return self._canonicalize_link_mark(mark, path=path)
        if mark_type == "highlight":
            return self._canonicalize_highlight_mark(mark, path=path)
        self._require_no_attrs(mark, path)
        return {"type": mark_type}

    def _canonicalize_link_mark(self, mark: dict, *, path: str) -> dict:
        attrs = self._require_attr_keys(
            mark, required={"href"}, optional=set(), path=path
        )
        href = attrs["href"]
        parsed = self._parse_url(href)
        if parsed is None or parsed.scheme not in LINK_ALLOWED_SCHEMES:
            raise InvalidDocumentOperation(
                "Link href must use http, https, mailto, or tel",
                path=f"{path}.attrs.href",
            )
        if parsed.scheme in {"http", "https"} and not parsed.netloc:
            raise InvalidDocumentOperation(
                "HTTP links must be absolute", path=f"{path}.attrs.href"
            )
        return {"type": "link", "attrs": {"href": href, **LINK_FIXED_ATTRIBUTES}}

    def _canonicalize_highlight_mark(self, mark: dict, *, path: str) -> dict:
        attrs = self._require_attr_keys(
            mark, required=set(), optional={"color"}, path=path
        )
        color = attrs.get("color")
        if color is not None and (
            not isinstance(color, str) or _HEX_COLOR.fullmatch(color) is None
        ):
            raise InvalidDocumentOperation(
                "Highlight color must be null or a six-digit hex color",
                path=f"{path}.attrs.color",
            )
        return {
            "type": "highlight",
            "attrs": {"color": color.lower() if color else None},
        }

    def _validate_mark_combinations(self, seen: set[str], *, path: str):
        if "code" in seen and len(seen) > 1:
            raise InvalidDocumentOperation(
                "Code marks cannot be combined with other marks", path=f"{path}.marks"
            )
        if {"subscript", "superscript"}.issubset(seen):
            raise InvalidDocumentOperation(
                "Text cannot be both subscript and superscript", path=f"{path}.marks"
            )

    def _parse_url(self, value: object) -> ParseResult | None:
        if not isinstance(value, str):
            return None
        try:
            return urlparse(value)
        except ValueError:
            return None

    def _require_leaf(self, node: dict, path: str):
        if node.get("content"):
            raise InvalidDocumentOperation(
                f"{node['type']} must not contain child nodes", path=f"{path}.content"
            )

    def _require_no_attrs(self, value: dict, path: str):
        if value.get("attrs"):
            raise InvalidDocumentOperation(
                "Attributes are not allowed here", path=f"{path}.attrs"
            )

    def _require_attr_keys(
        self,
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

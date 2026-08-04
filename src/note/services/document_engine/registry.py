"""Reviewed inventory and creation contract for ResearchHub's Tiptap editor."""

import hashlib
import json
from types import MappingProxyType

EDITOR_SCHEMA_VERSION = "researchhub-tiptap-2.27.2-v1"
LEGACY_SCHEMA_VERSION = "legacy-tiptap-v2"

# Conservative guards for synchronous, in-process operation. These limits apply to
# stored documents and model-created content alike; callers receive typed failures.
MAX_DOCUMENT_BYTES = 5_000_000
MAX_DOCUMENT_DEPTH = 64
MAX_DOCUMENT_NODES = 100_000
MAX_STRING_LENGTH = 1_000_000
MAX_CREATED_LANGUAGE_LENGTH = 64
MAX_READ_BLOCKS = 100
PREVIEW_LENGTH = 240

IMAGE_FIXED_ATTRIBUTES = MappingProxyType({"width": "100%", "align": "center"})
LINK_ALLOWED_SCHEMES = frozenset({"http", "https", "mailto", "tel"})
LINK_FIXED_ATTRIBUTES = MappingProxyType(
    {
        "target": "_blank",
        "rel": "noopener noreferrer nofollow",
        "class": None,
    }
)

ID_CAPABLE_NODES = frozenset({"paragraph", "heading", "codeBlock", "table"})

INVENTORY_NODES = MappingProxyType(
    {
        "doc": "block_children",
        "paragraph": "inline_children",
        "text": "text",
        "heading": "inline_children",
        "bulletList": "list_children",
        "orderedList": "list_children",
        "listItem": "block_children",
        "taskList": "list_children",
        "taskItem": "block_children",
        "hardBreak": "newline",
        "horizontalRule": "block_separator",
        "codeBlock": "code",
        "details": "block_children",
        "detailsSummary": "inline_children",
        "detailsContent": "block_children",
        "tableOfContentsNode": "empty",
        "imageUpload": "empty",
        "imageBlock": "image_alt",
        "emoji": "emoji_name",
        "table": "table",
        "tableRow": "table_row",
        "tableCell": "table_cell",
        "tableHeader": "table_cell",
        "columns": "block_children",
        "column": "block_children",
        "figcaption": "inline_children",
        "blockquoteFigure": "block_children",
        "quote": "block_children",
        "quoteCaption": "inline_children",
        "youtube": "youtube_url",
        "figure": "block_children",
    }
)

INVENTORY_MARKS = MappingProxyType(
    {
        "bold": (),
        "italic": (),
        "strike": (),
        "code": (),
        "underline": (),
        "subscript": (),
        "superscript": (),
        "link": ("href", "target", "rel", "class"),
        "highlight": ("color",),
        "textStyle": ("fontSize", "fontFamily", "color"),
    }
)

CREATABLE_NODES = frozenset(
    {
        "paragraph",
        "heading",
        "bulletList",
        "orderedList",
        "listItem",
        "taskList",
        "taskItem",
        "codeBlock",
        "horizontalRule",
        "hardBreak",
        "imageBlock",
        "text",
    }
)
CREATABLE_TOP_LEVEL_NODES = CREATABLE_NODES - {
    "hardBreak",
    "text",
    "listItem",
    "taskItem",
}
CREATABLE_MARKS = frozenset(
    {
        "bold",
        "italic",
        "underline",
        "strike",
        "code",
        "link",
        "subscript",
        "superscript",
        "highlight",
    }
)

# These names are part of the fingerprint so a behavioral registry change cannot be
# made without changing the fingerprint even when the Python implementation moves.
CREATION_RULES = MappingProxyType(
    {
        "paragraph": "inline-star;attrs-generated-id",
        "heading": "inline-star;level-1-6;attrs-generated-id",
        "bulletList": "listItem-plus;no-attrs",
        "orderedList": "listItem-plus;positive-start",
        "listItem": "paragraph-then-blocks;no-attrs",
        "taskList": "taskItem-plus;no-attrs",
        "taskItem": "paragraph-then-blocks;checked-bool",
        "codeBlock": "text-star-no-marks;language-null-or-short;attrs-generated-id",
        "horizontalRule": "leaf;no-attrs",
        "hardBreak": "inline-leaf;no-attrs",
        "imageBlock": "leaf;https-src;fixed-layout;optional-alt",
        "text": "non-empty;creatable-marks",
        "link": "http-https-mailto-tel;fixed-defaults",
        "highlight": "null-or-six-digit-hex",
    }
)


def _fingerprint() -> str:
    payload = {
        "schema_version": EDITOR_SCHEMA_VERSION,
        "nodes": dict(INVENTORY_NODES),
        "marks": {key: list(value) for key, value in INVENTORY_MARKS.items()},
        "id_capable_nodes": sorted(ID_CAPABLE_NODES),
        "creatable_nodes": sorted(CREATABLE_NODES),
        "creatable_marks": sorted(CREATABLE_MARKS),
        "creation_rules": dict(CREATION_RULES),
        "canonical_attributes": {
            "imageBlock": dict(IMAGE_FIXED_ATTRIBUTES),
            "link": dict(LINK_FIXED_ATTRIBUTES),
        },
        "link_allowed_schemes": sorted(LINK_ALLOWED_SCHEMES),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


SCHEMA_FINGERPRINT = _fingerprint()

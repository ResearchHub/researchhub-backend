"""Block-level edit operations for agent note editing.

The ``edit_note`` tool describes a change as operations on the top-level
blocks of the note as last read: ``insert`` blocks before an index,
``replace`` an inclusive index range, ``delete`` a range. Every index refers
to the read document -- one batch is applied as a whole, so earlier
operations never shift the indices later ones use. This is what lets the
model send only the blocks it changes instead of regenerating the document.

Parsing, bounds checking, and applying are separate steps because they have
different inputs: parsing sees only the tool call, bounds checking needs the
current block count (read under the note lock), and between the two the
caller schema-validates each operation's payload blocks with
``parse_edit_blocks``. All errors are ``ValueError`` with messages written
for the model, naming the path of the problem (``edits[0].blocks[3]...``).
Slips with one obvious meaning are fixed instead of rejected.
"""

import json
import re
from dataclasses import dataclass

from utils.prosemirror import get_schema, parse_blocks

INSERT = "insert"
REPLACE = "replace"
DELETE = "delete"


@dataclass
class BlockEdit:
    """One parsed operation; ``start``/``end`` are the wire ``from``/``to``."""

    op: str
    at: int | None = None
    start: int | None = None
    end: int | None = None
    blocks: list | None = None


def parse_block_edits(raw) -> list[BlockEdit]:
    """Validate the wire shape of an ``edits`` array into ``BlockEdit``s.

    Structural checks only; payload blocks are kept as sent so the caller
    can expand and schema-validate them, and index bounds wait for
    ``check_block_edits``.
    """
    if isinstance(raw, str):
        # Some models JSON-encode the array despite the schema; take it when
        # it decodes to one.
        raw = _decode_json_array(raw)
    if isinstance(raw, str):
        raise ValueError(
            "edits must be a non-empty array of operations, not a JSON string. "
            "Pass the array directly; do not quote or JSON-encode it. "
            'Example: {"edits": [{"op": "insert", "at": 0, '
            '"blocks": ["Paragraph text"]}]}'
        )
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "edits must be a non-empty array of operations "
            '(e.g. [{"op": "replace", "from": 1, "to": 2, "blocks": [...]}])'
        )
    return [_parse_edit(i, item) for i, item in enumerate(raw)]


def parse_edit_blocks(schema_name: str, blocks: list, path: str) -> list[dict]:
    """Fix, check, and schema-validate one edit's compact ``blocks``.

    Returns canonical block dicts as ``parse_blocks`` does. Each block is
    parsed on its own so a schema error names the block it is in.
    """
    schema = get_schema(schema_name)
    parsed = []
    for i, block in enumerate(blocks):
        block_path = f"{path}[{i}]"
        block = _prepare_child(schema, block, block_path)
        try:
            parsed.extend(parse_blocks(schema_name, [block]))
        except ValueError as exc:
            raise ValueError(
                f"{block_path}: {exc}{_content_hint(schema, str(exc))}"
            ) from exc
    return parsed


def check_block_edits(edits: list[BlockEdit], block_count: int) -> None:
    """Bounds- and overlap-check ``edits`` against ``block_count`` blocks."""
    for index, edit in enumerate(edits):
        _check_bounds(index, edit, block_count)
    _check_overlap(edits)


def apply_block_edits(blocks: list, edits: list[BlockEdit]) -> list:
    """Return ``blocks`` with checked ``edits`` applied.

    Inserts at the same position keep their order in ``edits``; an insert at
    a replaced range's start lands before the replacement blocks.
    """
    inserts: dict[int, list] = {}
    starts: dict[int, BlockEdit] = {}
    covered: set[int] = set()
    for edit in edits:
        if edit.op == INSERT:
            inserts.setdefault(edit.at, []).extend(edit.blocks)
        else:
            starts[edit.start] = edit
            covered.update(range(edit.start, edit.end + 1))

    result: list = []
    for position in range(len(blocks) + 1):
        result.extend(inserts.get(position, ()))
        if position in starts and starts[position].op == REPLACE:
            result.extend(starts[position].blocks)
        if position < len(blocks) and position not in covered:
            result.append(blocks[position])
    return result


# -- parsing ----------------------------------------------------------------


def _decode_json_array(raw: str) -> list | str:
    """The array ``raw`` encodes, else ``raw`` unchanged."""
    try:
        decoded = json.loads(raw)
    except ValueError:
        return raw
    return decoded if isinstance(decoded, list) else raw


def _parse_edit(index: int, item) -> BlockEdit:
    if not isinstance(item, dict):
        raise ValueError(f"edits[{index}]: each edit must be an object")
    op = item.get("op")
    if op not in (INSERT, REPLACE, DELETE):
        raise ValueError(
            f"edits[{index}]: op must be one of {INSERT!r}, {REPLACE!r}, {DELETE!r}"
        )
    if op == INSERT:
        if "from" in item or "to" in item:
            raise ValueError(
                f"edits[{index}]: insert positions with 'at'; "
                "'from'/'to' belong to replace and delete"
            )
        return BlockEdit(
            op=op,
            at=_parse_index(index, item, "at"),
            blocks=_parse_blocks_field(index, item),
        )
    if "at" in item:
        raise ValueError(
            f"edits[{index}]: {op} uses 'from'/'to'; 'at' belongs to insert"
        )
    start = _parse_index(index, item, "from")
    end = _parse_index(index, item, "to")
    if end < start:
        raise ValueError(f"edits[{index}]: 'to' must not be less than 'from'")
    if op == DELETE:
        if item.get("blocks"):
            raise ValueError(
                f"edits[{index}]: delete takes no blocks; "
                "use replace to substitute content"
            )
        return BlockEdit(op=op, start=start, end=end)
    return BlockEdit(
        op=op, start=start, end=end, blocks=_parse_blocks_field(index, item)
    )


def _parse_index(index: int, item: dict, field: str) -> int:
    value = item.get(field)
    # bool is an int subclass; true/false as an index is model confusion.
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(
            f"edits[{index}]: {field!r} must be a non-negative block index"
        )
    return value


def _parse_blocks_field(index: int, item: dict) -> list:
    blocks = item.get("blocks")
    if blocks == []:
        raise ValueError(
            f"edits[{index}]: 'blocks' is empty, so no content was sent. Put "
            "the new blocks in it; if a long section keeps arriving empty, "
            "send it in smaller edit_note calls. To remove blocks, use delete"
        )
    if not isinstance(blocks, list):
        raise ValueError(
            f"edits[{index}]: {item['op']} needs 'blocks', an array of new blocks"
        )
    return blocks


# -- payload blocks ------------------------------------------------------------

_TEXT_EXAMPLE = '{"type": "text", "text": "words", "marks": [{"type": "bold"}]}'
_TYPE_HINTS = {
    "blockquote": (
        "; for a quotation use "
        '{"type": "blockquoteFigure", "content": [{"type": "quote", '
        '"content": [paragraphs]}, {"type": "quoteCaption"}]}'
    ),
}
_JSON_TYPES = {
    dict: "object",
    list: "array",
    str: "string",
    bool: "boolean",
    int: "number",
    float: "number",
    type(None): "null",
}


def _prepare_child(schema, child, path: str):
    """``child`` with fixes applied; bare strings are text (or paragraphs)."""
    if isinstance(child, str):
        return child
    node_type = _checked_node_type(schema, child, path)
    _check_marks(schema, child.get("marks"), path)
    content = child.get("content")
    if content is None:
        return child
    if not isinstance(content, list):
        raise ValueError(f"{path}.content: expected an array of nodes")
    prepared = []
    for k, grandchild in enumerate(content):
        grandchild_path = f"{path}.content[{k}]"
        if grandchild == "":
            raise ValueError(f"{grandchild_path}: empty text is not allowed; omit it")
        prepared.append(_prepare_child(schema, grandchild, grandchild_path))
    if not node_type.inline_content and node_type.content_match.match_type(
        schema.nodes["paragraph"]
    ):
        prepared = _wrap_inline_runs(schema, prepared)
    return {**child, "content": prepared}


def _checked_node_type(schema, node, path: str):
    if not isinstance(node, dict):
        raise ValueError(
            f"{path}: expected a node object or a string, "
            f"got {_JSON_TYPES.get(type(node), type(node).__name__)}"
        )
    type_name = node.get("type")
    if not isinstance(type_name, str):
        raise ValueError(
            f'{path}: node needs "type", e.g. '
            '{"type": "paragraph", "content": ["text"]}'
        )
    node_type = schema.nodes.get(type_name)
    if node_type is None or node_type is schema.top_node_type:
        allowed = ", ".join(n for n in schema.nodes if n != schema.top_node_type.name)
        raise ValueError(
            f"{path}: unknown node type {type_name!r}"
            f"{_TYPE_HINTS.get(type_name, '')}; allowed types: {allowed}"
        )
    if node_type.is_text and not (isinstance(node.get("text"), str) and node["text"]):
        raise ValueError(
            f'{path}: text node needs "text", a non-empty string: {_TEXT_EXAMPLE}'
        )
    return node_type


def _check_marks(schema, marks, path: str) -> None:
    for j, mark in enumerate(marks if isinstance(marks, list) else ()):
        mark_type = mark.get("type") if isinstance(mark, dict) else None
        # A non-string type (e.g. a list) is unhashable for the lookup.
        if not isinstance(mark_type, str) or mark_type not in schema.marks:
            raise ValueError(
                f'{path}.marks[{j}]: a mark is {{"type": ...}} with type one of '
                f"{', '.join(schema.marks)}; got {json.dumps(mark)}"
            )


def _wrap_inline_runs(schema, content: list) -> list:
    # Bare text in a block container (listItem, tableCell, ...) can only
    # mean a paragraph.
    wrapped: list = []
    run: list = []
    for node in content:
        if _is_inline(schema, node):
            run.append(node)
            continue
        if run:
            wrapped.append({"type": "paragraph", "content": run})
            run = []
        wrapped.append(node)
    if run:
        wrapped.append({"type": "paragraph", "content": run})
    return wrapped


def _is_inline(schema, node) -> bool:
    if isinstance(node, str):
        return True
    node_type = schema.nodes.get(node.get("type"))
    return node_type is not None and node_type.is_inline


def _content_hint(schema, message: str) -> str:
    # prosemirror-py reports bad nesting as "Invalid content for node <name>".
    match = re.match(r"Invalid content for node (\w+)", message)
    node_type = schema.nodes.get(match.group(1)) if match else None
    if node_type is None or not node_type.spec.get("content"):
        return ""
    return f" ({node_type.name} content must match {node_type.spec['content']!r})"


# -- bounds and overlap -------------------------------------------------------


def _check_bounds(index: int, edit: BlockEdit, block_count: int) -> None:
    if edit.op == INSERT:
        if edit.at > block_count:
            raise ValueError(
                f"edits[{index}]: 'at' {edit.at} is out of range; valid insert "
                f"positions are 0..{block_count} (the note has "
                f"{block_count} blocks)"
            )
        return
    if block_count == 0:
        raise ValueError(
            f"edits[{index}]: the note has no blocks to {edit.op}; use insert"
        )
    if edit.end >= block_count:
        raise ValueError(
            f"edits[{index}]: block indices run 0..{block_count - 1} "
            f"(the note has {block_count} blocks)"
        )


def _check_overlap(edits: list[BlockEdit]) -> None:
    # Quadratic over the ops in one call, which is a handful in practice.
    for j, later in enumerate(edits):
        for i, earlier in enumerate(edits[:j]):
            if _conflicts(earlier, later):
                raise ValueError(
                    f"edits[{i}] and edits[{j}] overlap; each block can be "
                    "touched by at most one edit"
                )


def _conflicts(a: BlockEdit, b: BlockEdit) -> bool:
    if a.op == INSERT and b.op == INSERT:
        # Same-position inserts stack in the order they were sent.
        return False
    if a.op == INSERT or b.op == INSERT:
        insert, ranged = (a, b) if a.op == INSERT else (b, a)
        # Inserting at the range's start (before it) or right after its end
        # is unambiguous; inside the range there is no block left to anchor to.
        return ranged.start < insert.at <= ranged.end
    return a.start <= b.end and b.start <= a.end

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
caller schema-validates each operation's payload blocks. All errors are
``ValueError`` with messages written for the model.
"""

from dataclasses import dataclass

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
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "edits must be a non-empty array of operations "
            '(e.g. [{"op": "replace", "from": 1, "to": 2, "blocks": [...]}])'
        )
    return [_parse_edit(i, item) for i, item in enumerate(raw)]


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
    if not isinstance(blocks, list) or not blocks:
        raise ValueError(
            f"edits[{index}]: 'blocks' must be a non-empty array of new blocks"
        )
    return blocks


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

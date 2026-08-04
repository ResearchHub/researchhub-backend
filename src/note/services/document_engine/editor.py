"""Atomic block-subtree operations for Tiptap documents."""

import copy
import json
from collections import Counter

from note.services.document_engine.errors import InvalidDocumentOperation
from note.services.document_engine.registry import (
    CREATABLE_TOP_LEVEL_NODES,
    ID_CAPABLE_NODES,
)
from note.services.document_engine.validator import (
    normalize_created_ids,
    validate_created_node,
    validate_stored_document,
)

_OPERATION_KEYS = {
    "replace_block": frozenset({"op", "locator", "node"}),
    "insert_after": frozenset({"op", "locator", "node"}),
    "move_block": frozenset({"op", "locator", "after"}),
    "delete_block": frozenset({"op", "locator"}),
    "replace_note": frozenset({"op", "doc"}),
}


def apply_operations(
    doc: dict, operations: object
) -> tuple[dict, list[dict], list[dict]]:
    """Apply all operations to a copy, or raise without mutating the input."""

    if not isinstance(operations, list) or not operations:
        raise InvalidDocumentOperation(
            "operations must be a non-empty array", path="operations"
        )
    if (
        any(
            isinstance(operation, dict) and operation.get("op") == "replace_note"
            for operation in operations
        )
        and len(operations) != 1
    ):
        raise InvalidDocumentOperation(
            "replace_note must be the only operation in a request", path="operations"
        )

    working = copy.deepcopy(doc)
    results = []
    for operation_index, operation in enumerate(operations):
        path = f"operations[{operation_index}]"
        _validate_operation_shape(operation, path)
        op = operation["op"]
        if op == "replace_block":
            result = _replace_block(working, operation, path)
        elif op == "insert_after":
            result = _insert_after(working, operation, path)
        elif op == "move_block":
            result = _move_block(working, operation, path)
        elif op == "delete_block":
            result = _delete_block(working, operation, path)
        elif op == "replace_note":
            working = _replace_note(working, operation["doc"], path=f"{path}.doc")
            result = {"op": op, "status": "applied"}
        else:  # Shape validation makes this unreachable.
            raise AssertionError(f"Unhandled operation: {op}")
        results.append({"operation_index": operation_index, **result})

    normalized, id_warnings = normalize_created_ids(working)
    validated, _changed, validation_warnings = validate_stored_document(normalized)
    return validated, results, [*id_warnings, *validation_warnings]


def replace_note(base_doc: dict, submitted_doc: object) -> dict:
    """Validate full replacement with verbatim preservation for opaque blocks."""

    return _replace_note(base_doc, submitted_doc, path="doc")


def _replace_block(doc: dict, operation: dict, path: str) -> dict:
    content = doc["content"]
    index = _resolve_locator(content, operation["locator"], f"{path}.locator")
    target = content[index]
    if target["type"] not in CREATABLE_TOP_LEVEL_NODES:
        raise InvalidDocumentOperation(
            f"Opaque node type {target['type']!r} cannot be replaced",
            path=f"{path}.locator",
        )
    replacement = validate_created_node(operation["node"], path=f"{path}.node")
    target_id = target.get("attrs", {}).get("id")
    if replacement["type"] in ID_CAPABLE_NODES and isinstance(target_id, str):
        replacement.setdefault("attrs", {})["id"] = target_id
    content[index] = replacement
    return {
        "op": "replace_block",
        "status": "applied",
        "locator": operation["locator"],
        "index": index,
    }


def _insert_after(doc: dict, operation: dict, path: str) -> dict:
    content = doc["content"]
    locator = operation["locator"]
    if locator == "doc:start":
        insert_index = 0
    else:
        insert_index = _resolve_locator(content, locator, f"{path}.locator") + 1
    node = validate_created_node(operation["node"], path=f"{path}.node")
    content.insert(insert_index, node)
    return {
        "op": "insert_after",
        "status": "applied",
        "after": locator,
        "index": insert_index,
    }


def _move_block(doc: dict, operation: dict, path: str) -> dict:
    content = doc["content"]
    locator = operation["locator"]
    after = operation["after"]
    if locator == after:
        raise InvalidDocumentOperation(
            "A block cannot be moved after itself", path=f"{path}.after"
        )
    source_index = _resolve_locator(content, locator, f"{path}.locator")
    after_index = (
        None
        if after == "doc:start"
        else _resolve_locator(content, after, f"{path}.after")
    )
    node = content.pop(source_index)
    if after_index is None:
        destination_index = 0
    elif after_index > source_index:
        destination_index = after_index
    else:
        destination_index = after_index + 1
    content.insert(destination_index, node)
    return {
        "op": "move_block",
        "status": "applied",
        "locator": locator,
        "after": after,
        "from_index": source_index,
        "index": destination_index,
    }


def _delete_block(doc: dict, operation: dict, path: str) -> dict:
    content = doc["content"]
    index = _resolve_locator(content, operation["locator"], f"{path}.locator")
    content.pop(index)
    return {
        "op": "delete_block",
        "status": "applied",
        "locator": operation["locator"],
        "index": index,
    }


def _replace_note(base_doc: dict, submitted_doc: object, *, path: str) -> dict:
    validate_stored_document(submitted_doc)
    candidate = copy.deepcopy(submitted_doc)
    assert isinstance(candidate, dict)  # Validated above.
    base_blocks = Counter(_canonical(node) for node in base_doc.get("content", []))
    accepted = []
    for index, node in enumerate(candidate.get("content", [])):
        canonical = _canonical(node)
        if base_blocks[canonical]:
            base_blocks[canonical] -= 1
            accepted.append(copy.deepcopy(node))
            continue
        try:
            accepted.append(
                validate_created_node(node, path=f"{path}.content[{index}]")
            )
        except InvalidDocumentOperation as exc:
            raise InvalidDocumentOperation(
                "Full-note replacement may only create whitelisted blocks or "
                "preserve base blocks verbatim",
                path=exc.path or f"{path}.content[{index}]",
            ) from exc
    return {"type": "doc", "content": accepted}


def _validate_operation_shape(operation: object, path: str):
    if not isinstance(operation, dict):
        raise InvalidDocumentOperation("Every operation must be an object", path=path)
    if any(not isinstance(key, str) for key in operation):
        raise InvalidDocumentOperation(
            "Operation field names must be strings", path=path
        )
    op = operation.get("op")
    if not isinstance(op, str):
        raise InvalidDocumentOperation(
            "Document operation name must be a string", path=f"{path}.op"
        )
    expected_keys = _OPERATION_KEYS.get(op)
    if expected_keys is None:
        raise InvalidDocumentOperation(
            f"Unsupported document operation: {op!r}", path=f"{path}.op"
        )
    missing = expected_keys - set(operation)
    extra = set(operation) - expected_keys
    if missing:
        raise InvalidDocumentOperation(
            f"Operation is missing fields: {sorted(missing)}", path=path
        )
    if extra:
        raise InvalidDocumentOperation(
            f"Operation has unsupported fields: {sorted(extra)}", path=path
        )


def _resolve_locator(content: list[dict], locator: object, path: str) -> int:
    if not isinstance(locator, str) or not locator:
        raise InvalidDocumentOperation("Locator must be a non-empty string", path=path)
    if locator.startswith("i:"):
        raw_index = locator[2:]
        if not raw_index.isdigit():
            raise InvalidDocumentOperation(
                f"Malformed index locator: {locator!r}", path=path
            )
        index = int(raw_index)
        if index >= len(content):
            raise InvalidDocumentOperation(
                f"Locator does not name a block: {locator!r}", path=path
            )
        return index
    if locator == "doc:start":
        raise InvalidDocumentOperation(
            "doc:start may only be used as an insertion destination", path=path
        )
    matches = [
        index
        for index, node in enumerate(content)
        if node.get("attrs", {}).get("id") == locator
    ]
    if len(matches) != 1:
        raise InvalidDocumentOperation(
            f"Locator does not uniquely name a block: {locator!r}", path=path
        )
    return matches[0]


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

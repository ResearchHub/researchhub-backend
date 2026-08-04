"""Deterministic normalization for durable document metadata."""

import copy
import json
import uuid
from collections.abc import Iterable

from note.services.document_engine.registry import ID_CAPABLE_NODES

_ID_NAMESPACE = uuid.UUID("b1ab26a0-b48b-5cba-9618-d9675d455b95")


class DocumentNormalizer:
    """Copy a document and assign deterministic IDs where required."""

    def normalize(self, doc: dict) -> tuple[dict, list[dict]]:
        normalized = copy.deepcopy(doc)
        warnings = self._normalize_ids(normalized)
        return normalized, warnings

    def _normalize_ids(self, doc: dict) -> list[dict]:
        seen: set[str] = set()
        warnings: list[dict] = []
        for node, path in self._walk_nodes(doc):
            if node["type"] not in ID_CAPABLE_NODES:
                continue
            attrs = node.setdefault("attrs", {})
            current_id = attrs.get("id")
            reason = self._repair_reason(current_id, seen)
            if reason is None:
                seen.add(current_id)
                continue

            new_id = self._deterministic_id(node, path, seen)
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

    def _repair_reason(self, current_id: object, seen: set[str]) -> str | None:
        if not isinstance(current_id, str) or not current_id.strip():
            return "missing_node_id"
        if current_id in seen:
            return "duplicate_node_id"
        return None

    def _deterministic_id(self, node: dict, path: str, seen: set[str]) -> str:
        basis = copy.deepcopy(node)
        basis.setdefault("attrs", {}).pop("id", None)
        canonical = json.dumps(basis, sort_keys=True, separators=(",", ":"))
        attempt = 0
        while True:
            candidate = str(uuid.uuid5(_ID_NAMESPACE, f"{path}:{canonical}:{attempt}"))
            if candidate not in seen:
                return candidate
            attempt += 1

    def _walk_nodes(self, node: dict, path: str = "doc") -> Iterable[tuple[dict, str]]:
        yield node, path
        for index, child in enumerate(node.get("content", [])):
            yield from self._walk_nodes(child, f"{path}.content[{index}]")

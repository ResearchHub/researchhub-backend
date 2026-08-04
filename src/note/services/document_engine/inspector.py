"""Non-destructive inspection of stored editor documents."""

from collections.abc import Iterable

from note.services.document_engine.registry import (
    CREATABLE_NODES,
    INVENTORY_MARKS,
    INVENTORY_NODES,
)


class DocumentInspector:
    """Report preservation and projection warnings for stored content."""

    def inspect(self, doc: dict) -> list[dict]:
        warnings: list[dict] = []
        warned: set[tuple[str, str]] = set()
        for node, path in self._walk_nodes(doc):
            self._inspect_node_type(node, path, warnings, warned)
            self._append_projection_warning(warnings, node, path)
            self._inspect_marks(node, path, warnings, warned)
        return warnings

    def _inspect_node_type(
        self,
        node: dict,
        path: str,
        warnings: list[dict],
        warned: set[tuple[str, str]],
    ):
        node_type = node["type"]
        if node_type not in INVENTORY_NODES:
            self._append_type_warning(
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
            self._append_type_warning(
                warnings,
                warned,
                code="opaque_node_type",
                type_name=node_type,
                path=path,
                message=f"Node type {node_type!r} is opaque and was preserved verbatim",
            )

    def _inspect_marks(
        self,
        node: dict,
        path: str,
        warnings: list[dict],
        warned: set[tuple[str, str]],
    ):
        for mark_index, mark in enumerate(node.get("marks", [])):
            mark_type = mark["type"]
            if mark_type not in INVENTORY_MARKS:
                self._append_type_warning(
                    warnings,
                    warned,
                    code="unknown_mark_type",
                    type_name=mark_type,
                    path=f"{path}.marks[{mark_index}]",
                    message=(
                        f"Mark type {mark_type!r} is unknown and was preserved verbatim"
                    ),
                )

    def _append_projection_warning(self, warnings: list[dict], node: dict, path: str):
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
                        f"Attribute {projected_attribute!r} could not be projected "
                        "as text"
                    ),
                }
            )

    def _append_type_warning(
        self,
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

    def _walk_nodes(self, node: dict, path: str = "doc") -> Iterable[tuple[dict, str]]:
        yield node, path
        for index, child in enumerate(node.get("content", [])):
            yield from self._walk_nodes(child, f"{path}.content[{index}]")

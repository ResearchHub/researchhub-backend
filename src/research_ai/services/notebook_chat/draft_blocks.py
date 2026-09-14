"""Bounded note-block snapshots from incomplete tool arguments."""

import json

import jiter

from utils.prosemirror import expand_blocks

MAX_INPUT_BYTES = 128_000


class ToolDraftBlocks:
    """Parse partial JSON; leave presentation to the editor's own renderer."""

    def __init__(self):
        self._input = bytearray()
        self._last: list[dict] = []

    def feed(self, fragment: str) -> None:
        room = MAX_INPUT_BYTES - len(self._input)
        if room > 0:
            self._input.extend(fragment.encode("utf-8")[:room])

    def snapshot(self) -> list[dict]:
        try:
            payload = jiter.from_json(
                bytes(self._input), partial_mode="trailing-strings"
            )
            edits = payload.get("edits", []) if isinstance(payload, dict) else []
            blocks = []
            for edit in edits if isinstance(edits, list) else []:
                if isinstance(edit, dict) and isinstance(edit.get("blocks"), list):
                    blocks.extend(edit["blocks"])
            expanded = expand_blocks(blocks)
            # Expansion of compact strings must not inflate a stream frame
            # without limit. Incomplete nodes are handled by the preview UI.
            if len(json.dumps(expanded).encode("utf-8")) <= MAX_INPUT_BYTES:
                self._last = expanded
        except (ValueError, TypeError, RecursionError):
            pass
        return self._last

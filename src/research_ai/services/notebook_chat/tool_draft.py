"""Readable preview of a tool call's arguments while the model writes them.

A notebook turn spends most of its output tokens inside ``edit_note``
arguments -- the rewritten paragraphs travel as JSON -- and none of that is
text the provider streams as prose. Showing the raw JSON would be noise, so
:class:`ToolDraftTextExtractor` scans the argument fragments incrementally and
surfaces only the strings that are note content:

- bare string elements of any array (compact blocks and inline text runs), and
- values of a ``"text"`` key (marked text nodes).

Everything else -- ``op``/``type`` enums, attribute values, ids -- is skipped.
Consecutive strings are separated by a blank line so the preview reads as
paragraphs. The scanner tolerates fragments split anywhere, including inside
escape sequences, and never raises on malformed input: the preview is
best-effort and a broken stream simply stops yielding text.
"""

from research_ai.services.note_tools import EDIT_NOTE

# Tools whose arguments carry note prose worth previewing. Other tools' inputs
# (queries, ids, code) still announce themselves via the draft item but surface
# no text.
TOOL_DRAFT_PROSE_TOOLS = frozenset({EDIT_NOTE})

_PROSE_KEY = "text"
_PARAGRAPH_BREAK = "\n\n"
_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

_ROLE_KEY = "key"
_ROLE_PROSE = "prose"
_ROLE_SKIP = "skip"


class ToolDraftTextExtractor:
    """Feed JSON fragments; get back the prose written since the last feed."""

    def __init__(self):
        # One entry per open container: ("object", expecting_key) or ("array",).
        self._stack: list[list] = []
        self._current_key: str | None = None
        self._in_string = False
        self._role = _ROLE_SKIP
        self._key_chars: list[str] = []
        self._escaped = False
        self._unicode_digits: list[str] | None = None
        self._high_surrogate: str | None = None
        self._emitted_any = False
        self._break_pending = False

    def feed(self, fragment: str) -> str:
        out: list[str] = []
        for char in fragment:
            if self._in_string:
                self._string_char(char, out)
            else:
                self._structural_char(char)
        return "".join(out)

    # -- inside a string ---------------------------------------------------

    def _string_char(self, char: str, out: list[str]) -> None:
        if self._unicode_digits is not None:
            self._unicode_digits.append(char)
            if len(self._unicode_digits) == 4:
                self._finish_unicode_escape(out)
            return
        if self._escaped:
            self._escaped = False
            if char == "u":
                self._unicode_digits = []
                return
            self._emit(_SIMPLE_ESCAPES.get(char, char), out)
            return
        if char == "\\":
            self._escaped = True
            return
        if char == '"':
            self._end_string()
            return
        self._emit(char, out)

    def _finish_unicode_escape(self, out: list[str]) -> None:
        digits = "".join(self._unicode_digits or [])
        self._unicode_digits = None
        try:
            code = int(digits, 16)
        except ValueError:
            return
        if 0xD800 <= code <= 0xDBFF:
            # High surrogate: hold until its low half arrives.
            self._high_surrogate = chr(code)
            return
        if 0xDC00 <= code <= 0xDFFF and self._high_surrogate is not None:
            pair = self._high_surrogate + chr(code)
            self._high_surrogate = None
            self._emit(pair.encode("utf-16", "surrogatepass").decode("utf-16"), out)
            return
        self._high_surrogate = None
        self._emit(chr(code), out)

    def _emit(self, text: str, out: list[str]) -> None:
        if self._role == _ROLE_KEY:
            self._key_chars.append(text)
            return
        if self._role != _ROLE_PROSE:
            return
        if self._break_pending:
            out.append(_PARAGRAPH_BREAK)
            self._break_pending = False
        out.append(text)
        self._emitted_any = True

    def _end_string(self) -> None:
        self._in_string = False
        self._high_surrogate = None
        if self._role == _ROLE_KEY:
            self._current_key = "".join(self._key_chars)
            self._key_chars = []
        elif self._role == _ROLE_PROSE and self._emitted_any:
            # Separate this string from the next prose string, but never
            # emit a leading break: an empty string is not a paragraph.
            self._break_pending = True
        self._role = _ROLE_SKIP

    # -- between strings -----------------------------------------------------

    def _structural_char(self, char: str) -> None:
        top = self._stack[-1] if self._stack else None
        if char == '"':
            self._in_string = True
            self._escaped = False
            self._role = self._string_role(top)
            if self._role == _ROLE_KEY:
                self._key_chars = []
        elif char == "{":
            self._stack.append(["object", True])
        elif char == "[":
            self._stack.append(["array"])
        elif char in "}]":
            if self._stack:
                self._stack.pop()
            self._current_key = None
        elif char == ":":
            if top is not None and top[0] == "object":
                top[1] = False
        elif char == "," and top is not None and top[0] == "object":
            top[1] = True
            self._current_key = None

    def _string_role(self, top: list | None) -> str:
        """What the string opening now is: a key, prose, or ignorable."""
        if top is None:
            return _ROLE_SKIP
        if top[0] == "object":
            if top[1]:
                return _ROLE_KEY
            return _ROLE_PROSE if self._current_key == _PROSE_KEY else _ROLE_SKIP
        return _ROLE_PROSE

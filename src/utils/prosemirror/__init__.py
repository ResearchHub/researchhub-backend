"""ProseMirror schemas exported from the web frontend.

The JSON specs under ``schemas/`` are generated in the ResearchHub/web repo
by ``npm run schema:export`` from the same TipTap extension sets the editors
run (see ``schemas/prosemirror/README.md`` there, and ``schemas/README.md``
here for how to update the vendored copies). They let backend code parse,
validate, and write editor documents against the exact schema the frontend
enforces, via `prosemirror-py <https://github.com/fellowapp/prosemirror-py>`_.

Usage::

    from utils.prosemirror import COMMENT_EDITOR, parse_document

    node = parse_document(COMMENT_EDITOR, comment_json)  # raises ValueError

Schema validity is structural only: it guarantees known node/mark types,
required attributes, and legal nesting — not that a mention's user id exists
or that a link is safe. That remains application-level validation. Note that
unrecognized attributes are silently stripped rather than rejected.
"""

from utils.prosemirror.loader import (
    BLOCK_EDITOR,
    COMMENT_EDITOR,
    get_schema,
    parse_document,
)

__all__ = [
    "BLOCK_EDITOR",
    "COMMENT_EDITOR",
    "get_schema",
    "parse_document",
]

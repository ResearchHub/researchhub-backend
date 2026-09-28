import itertools
import unittest

from utils.prosemirror import (
    BLOCK_EDITOR,
    compact_blocks,
    is_trailing_paragraph,
    normalize_block_document,
    parse_document,
)


def _ids():
    counter = itertools.count(1)
    return lambda: f"id-{next(counter)}"


def _heading(text, **attrs):
    node = {"type": "heading", "attrs": {"level": 2, **attrs}}
    if text:
        node["content"] = [{"type": "text", "text": text}]
    return node


def _paragraph(text=None, **attrs):
    node = {"type": "paragraph"}
    if attrs:
        node["attrs"] = attrs
    if text:
        node["content"] = [{"type": "text", "text": text}]
    return node


class NormalizeBlockDocumentTests(unittest.TestCase):
    def test_stamps_ids_like_the_editor(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                _heading("Intro"),
                _heading(""),
                {
                    "type": "bulletList",
                    "content": [
                        {"type": "listItem", "content": [_paragraph("nested")]}
                    ],
                },
                {"type": "codeBlock", "content": [{"type": "text", "text": "x"}]},
                _paragraph("last"),
            ],
        }

        # Act
        normalized = normalize_block_document(doc, generate_id=_ids())

        # Assert: a titled heading's id doubles as its TOC id; an empty
        # heading gets only a unique id; nested blocks are stamped too.
        content = normalized["content"]
        self.assertEqual(content[0]["attrs"]["id"], "id-1")
        self.assertEqual(content[0]["attrs"]["data-toc-id"], "id-1")
        self.assertEqual(content[1]["attrs"], {"level": 2, "id": "id-2"})
        nested = content[2]["content"][0]["content"][0]
        self.assertEqual(nested["attrs"], {"id": "id-3"})
        self.assertEqual(content[3]["attrs"], {"id": "id-4"})
        self.assertEqual(content[4]["attrs"], {"id": "id-5"})
        self.assertEqual(len(content), 5)
        parse_document(BLOCK_EDITOR, normalized)

    def test_keeps_existing_ids_and_replaces_duplicates(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                _heading("A", id="h", **{"data-toc-id": "t"}),
                _heading("B", id="h2", **{"data-toc-id": "t"}),
                _paragraph("one", id="p"),
                _paragraph("two", id="p"),
            ],
        }

        # Act
        normalized = normalize_block_document(doc, generate_id=_ids())

        # Assert
        attrs = [block["attrs"] for block in normalized["content"]]
        self.assertEqual(attrs[0], {"level": 2, "id": "h", "data-toc-id": "t"})
        self.assertEqual(attrs[1], {"level": 2, "id": "id-1", "data-toc-id": "id-1"})
        self.assertEqual(attrs[2], {"id": "p"})
        self.assertEqual(attrs[3], {"id": "id-2"})

    def test_appends_a_trailing_paragraph_unless_one_ends_the_document(self):
        # Arrange
        ends_in_heading = {"type": "doc", "content": [_heading("Only")]}
        ends_in_paragraph = {"type": "doc", "content": [_paragraph("Only")]}

        # Act
        appended = normalize_block_document(ends_in_heading, generate_id=_ids())
        unchanged = normalize_block_document(ends_in_paragraph, generate_id=_ids())
        empty = normalize_block_document({"type": "doc"}, generate_id=_ids())

        # Assert
        self.assertEqual(len(appended["content"]), 2)
        self.assertEqual(
            appended["content"][-1], {"type": "paragraph", "attrs": {"id": "id-2"}}
        )
        self.assertEqual(len(unchanged["content"]), 1)
        self.assertEqual(
            empty["content"], [{"type": "paragraph", "attrs": {"id": "id-1"}}]
        )

    def test_normalizing_is_idempotent_and_leaves_input_untouched(self):
        # Arrange
        doc = {"type": "doc", "content": [_heading("Intro")]}

        # Act
        once = normalize_block_document(doc)
        twice = normalize_block_document(once)

        # Assert
        self.assertEqual(once, twice)
        self.assertEqual(doc, {"type": "doc", "content": [_heading("Intro")]})


class IsTrailingParagraphTests(unittest.TestCase):
    def test_only_an_empty_default_paragraph_qualifies(self):
        # Act & Assert
        self.assertTrue(is_trailing_paragraph({"type": "paragraph"}))
        self.assertTrue(
            is_trailing_paragraph(
                {"type": "paragraph", "attrs": {"id": "x", "textAlign": None}}
            )
        )
        self.assertFalse(is_trailing_paragraph(_paragraph("text")))
        self.assertFalse(
            is_trailing_paragraph(
                {"type": "paragraph", "attrs": {"textAlign": "center"}}
            )
        )
        self.assertFalse(is_trailing_paragraph({"type": "heading"}))


class CompactOmitAttrsTests(unittest.TestCase):
    def test_omitted_attrs_are_dropped_at_every_depth(self):
        # Arrange
        doc = normalize_block_document(
            {
                "type": "doc",
                "content": [
                    _heading("Intro"),
                    _paragraph("Body"),
                    {
                        "type": "blockquoteFigure",
                        "content": [
                            {"type": "quote", "content": [_paragraph("q")]},
                            {"type": "quoteCaption"},
                        ],
                    },
                ],
            }
        )

        # Act
        blocks = compact_blocks(BLOCK_EDITOR, doc, omit_attrs={"id", "data-toc-id"})

        # Assert
        self.assertEqual(
            blocks,
            [
                {"type": "heading", "attrs": {"level": 2}, "content": ["Intro"]},
                "Body",
                {
                    "type": "blockquoteFigure",
                    "content": [
                        {
                            "type": "quote",
                            "content": [{"type": "paragraph", "content": ["q"]}],
                        },
                        {"type": "quoteCaption"},
                    ],
                },
                "",
            ],
        )

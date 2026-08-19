import unittest

from utils.prosemirror import (
    BLOCK_EDITOR,
    COMMENT_EDITOR,
    get_schema,
    parse_document,
)

COMMENT_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "sectionHeader",
            "attrs": {"sectionId": "s1", "title": "Impact", "rating": 4},
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Great work "},
                {"type": "mention", "attrs": {"id": "123", "label": "Jane Doe"}},
                {"type": "text", "text": ", see "},
                {
                    "type": "richLink",
                    "attrs": {"url": "https://example.com/paper"},
                },
                {
                    "type": "text",
                    "marks": [{"type": "bold"}],
                    "text": " (important)",
                },
            ],
        },
        {"type": "codeBlock", "content": [{"type": "text", "text": "print('hi')"}]},
    ],
}


class ProseMirrorSchemaTests(unittest.TestCase):
    def test_schemas_load_with_expected_types(self):
        block = get_schema(BLOCK_EDITOR)
        comment = get_schema(COMMENT_EDITOR)

        for node_name in ("doc", "paragraph", "text", "imageBlock", "blockMath"):
            self.assertIn(node_name, block.nodes)
        for node_name in ("doc", "mention", "richLink", "sectionHeader"):
            self.assertIn(node_name, comment.nodes)
        for mark_name in ("bold", "italic", "link"):
            self.assertIn(mark_name, block.marks)
            self.assertIn(mark_name, comment.marks)

    def test_get_schema_caches_instances(self):
        self.assertIs(get_schema(COMMENT_EDITOR), get_schema(COMMENT_EDITOR))

    def test_parse_document_round_trips_and_fills_defaults(self):
        node = parse_document(COMMENT_EDITOR, COMMENT_DOC)

        mention = node.child(1).child(1)
        self.assertEqual(mention.attrs["id"], "123")
        # Defaults the input omitted are filled in from the schema.
        self.assertEqual(mention.attrs["mentionSuggestionChar"], "@")
        self.assertEqual(node.child(2).attrs["language"], "javascript")

        round_tripped = node.to_json()
        self.assertEqual(round_tripped["type"], "doc")
        self.assertEqual(len(round_tripped["content"]), 3)

    def test_programmatic_document_construction(self):
        block = get_schema(BLOCK_EDITOR)
        doc = block.node(
            "doc",
            None,
            [
                block.node("heading", {"level": 1}, [block.text("My note")]),
                block.node("paragraph", None, [block.text("Body text")]),
                block.node("imageBlock", {"src": "https://example.com/img.png"}),
            ],
        )
        doc.check()
        self.assertIsNone(doc.child(2).attrs["alt"])

    def test_unknown_node_type_rejected(self):
        # imageBlock exists in the block schema but not the comment schema.
        bad_doc = {"type": "doc", "content": [{"type": "imageBlock"}]}
        with self.assertRaises(ValueError):
            parse_document(COMMENT_EDITOR, bad_doc)

    def test_invalid_nesting_rejected(self):
        bad_doc = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "paragraph"}]}],
        }
        with self.assertRaises(ValueError):
            parse_document(COMMENT_EDITOR, bad_doc)

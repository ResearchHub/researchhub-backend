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
        # Act
        block = get_schema(BLOCK_EDITOR)
        comment = get_schema(COMMENT_EDITOR)

        # Assert
        for node_name in ("doc", "paragraph", "text", "imageBlock", "blockMath"):
            self.assertIn(node_name, block.nodes)
        for node_name in ("doc", "mention", "richLink", "sectionHeader"):
            self.assertIn(node_name, comment.nodes)
        for mark_name in ("bold", "italic", "link"):
            self.assertIn(mark_name, block.marks)
            self.assertIn(mark_name, comment.marks)

    def test_get_schema_caches_instances(self):
        # Act
        first = get_schema(COMMENT_EDITOR)
        second = get_schema(COMMENT_EDITOR)

        # Assert
        self.assertIs(first, second)

    def test_parse_document_round_trips_and_fills_defaults(self):
        # Act
        node = parse_document(COMMENT_EDITOR, COMMENT_DOC)
        round_tripped = node.to_json()

        # Assert
        mention = node.child(1).child(1)
        self.assertEqual(mention.attrs["id"], "123")
        # Defaults the input omitted are filled in from the schema.
        self.assertEqual(mention.attrs["mentionSuggestionChar"], "@")
        self.assertEqual(node.child(2).attrs["language"], "javascript")
        self.assertEqual(round_tripped["type"], "doc")
        self.assertEqual(len(round_tripped["content"]), 3)

    def test_programmatic_document_construction(self):
        # Arrange
        block = get_schema(BLOCK_EDITOR)

        # Act
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

        # Assert
        self.assertIsNone(doc.child(2).attrs["alt"])

    def test_non_document_root_rejected(self):
        # Arrange
        fragment = {
            "type": "paragraph",
            "content": [{"type": "text", "text": "not a doc"}],
        }

        # Act & Assert
        with self.assertRaisesRegex(ValueError, "expected top-level 'doc'"):
            parse_document(COMMENT_EDITOR, fragment)

    def test_unknown_node_attribute_rejected(self):
        # Arrange
        # prosemirror-py would silently drop the misspelled key, leaving a
        # mention whose real id attribute is None.
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "mention",
                            "attrs": {"usrId": "1", "label": "x"},
                        }
                    ],
                }
            ],
        }

        # Act & Assert
        with self.assertRaisesRegex(ValueError, "usrId"):
            parse_document(COMMENT_EDITOR, doc)

    def test_unknown_mark_attribute_rejected(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "see docs",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {
                                        "href": "https://example.com",
                                        "bogus": 1,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        # Act & Assert
        with self.assertRaisesRegex(ValueError, "bogus"):
            parse_document(COMMENT_EDITOR, doc)

    def test_misspelled_content_key_rejected(self):
        # Arrange
        # from_json would ignore "contents" and build an empty paragraph.
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "contents": [{"type": "text", "text": "lost"}],
                }
            ],
        }

        # Act & Assert
        with self.assertRaisesRegex(ValueError, "keys on node 'paragraph': contents"):
            parse_document(COMMENT_EDITOR, doc)

    def test_misspelled_marks_key_rejected(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "x", "mark": [{"type": "bold"}]}
                    ],
                }
            ],
        }

        # Act & Assert
        with self.assertRaisesRegex(ValueError, "keys on node 'text': mark"):
            parse_document(COMMENT_EDITOR, doc)

    def test_misspelled_mark_attrs_key_rejected(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "x",
                            "marks": [
                                {"type": "link", "attr": {"href": "https://a.b"}}
                            ],
                        }
                    ],
                }
            ],
        }

        # Act & Assert
        with self.assertRaisesRegex(ValueError, "keys on mark 'link': attr"):
            parse_document(COMMENT_EDITOR, doc)

    def test_malformed_json_rejected_with_value_error(self):
        # Arrange
        # Shapes where prosemirror-py itself raises KeyError/AttributeError,
        # which parse_document must translate to the advertised ValueError.
        def wrap(inner):
            return {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [inner]}],
            }

        malformed = {
            "node missing type": wrap({"text": "no type"}),
            "text node missing text": wrap({"type": "text"}),
            "non-dict content item": wrap(5),
            "non-dict attrs": wrap({"type": "mention", "attrs": 5}),
        }

        # Act & Assert
        for name, doc in malformed.items():
            with (
                self.subTest(name),
                self.assertRaisesRegex(ValueError, "malformed document JSON"),
            ):
                parse_document(COMMENT_EDITOR, doc)

    def test_falsy_non_container_values_rejected(self):
        # Arrange
        # Falsy wrong-typed containers would otherwise read as absent and
        # normalize instead of failing.
        def wrap(inner):
            return {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [inner]}],
            }

        malformed = {
            "attrs as list": wrap({"type": "mention", "attrs": []}),
            "attrs as string": wrap({"type": "mention", "attrs": ""}),
            "attrs as bool": wrap({"type": "mention", "attrs": False}),
            "marks as bool": wrap({"type": "text", "text": "x", "marks": False}),
            "content as bool": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": False}],
            },
        }

        # Act & Assert
        for name, doc in malformed.items():
            with (
                self.subTest(name),
                self.assertRaisesRegex(ValueError, "malformed"),
            ):
                parse_document(COMMENT_EDITOR, doc)

    def test_null_containers_treated_as_absent(self):
        # Arrange
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": None,
                    "content": [{"type": "text", "text": "x", "marks": None}],
                }
            ],
        }

        # Act
        node = parse_document(COMMENT_EDITOR, doc)

        # Assert
        self.assertEqual(node.child(0).child(0).text, "x")

    def test_unknown_node_type_rejected(self):
        # Arrange
        # imageBlock exists in the block schema but not the comment schema.
        bad_doc = {"type": "doc", "content": [{"type": "imageBlock"}]}

        # Act & Assert
        with self.assertRaises(ValueError):
            parse_document(COMMENT_EDITOR, bad_doc)

    def test_invalid_nesting_rejected(self):
        # Arrange
        bad_doc = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "paragraph"}]}],
        }

        # Act & Assert
        with self.assertRaises(ValueError):
            parse_document(COMMENT_EDITOR, bad_doc)

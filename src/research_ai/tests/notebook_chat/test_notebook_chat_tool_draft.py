import unittest

from research_ai.services.notebook_chat.tool_draft import ToolDraftTextExtractor


def _feed_all(extractor: ToolDraftTextExtractor, chunks) -> str:
    return "".join(extractor.feed(chunk) for chunk in chunks)


class ToolDraftTextExtractorTests(unittest.TestCase):
    def test_extracts_bare_block_strings_and_skips_scalars_and_enums(self):
        # Arrange
        payload = (
            '{"note_id": 1524, "expected_version_id": 7381, "edits": ['
            '{"op": "replace", "from": 3, "to": 4, '
            '"blocks": ["First paragraph.", "Second paragraph."]}]}'
        )

        # Act
        text = ToolDraftTextExtractor().feed(payload)

        # Assert: prose only, one paragraph break between strings.
        self.assertEqual(text, "First paragraph.\n\nSecond paragraph.")

    def test_extracts_text_key_values_but_not_other_object_values(self):
        # Arrange
        payload = (
            '{"edits": [{"op": "insert", "at": 0, "blocks": ['
            '{"type": "heading", "attrs": {"level": 2}, "content": ['
            '{"type": "text", "text": "Discussion", '
            '"marks": [{"type": "bold"}]}]}]}]}'
        )

        # Act
        text = ToolDraftTextExtractor().feed(payload)

        # Assert: node/mark type names and attrs never surface.
        self.assertEqual(text, "Discussion")

    def test_fragments_split_anywhere_reassemble_including_escapes(self):
        # Arrange
        payload = '{"blocks": ["a \\"quoted\\" word", "tab\\there \\u00e9"]}'
        chunks = [payload[i : i + 3] for i in range(0, len(payload), 3)]

        # Act
        text = _feed_all(ToolDraftTextExtractor(), chunks)

        # Assert
        self.assertEqual(text, 'a "quoted" word\n\ntab\there é')

    def test_surrogate_pair_escapes_decode_to_one_character(self):
        # Arrange
        payload = '{"blocks": ["\\ud83d\\ude00"]}'

        # Act
        text = ToolDraftTextExtractor().feed(payload)

        # Assert
        self.assertEqual(text, "\U0001f600")

    def test_empty_strings_produce_no_stray_paragraph_breaks(self):
        # Arrange
        payload = '{"blocks": ["", "one", "", "two"]}'

        # Act
        text = ToolDraftTextExtractor().feed(payload)

        # Assert
        self.assertEqual(text, "one\n\ntwo")

    def test_keys_with_escapes_do_not_leak_into_prose(self):
        # Arrange: a key containing the word "text" is still just a key.
        payload = '{"con\\u0074ent": ["prose"], "context": "skipped"}'

        # Act
        text = ToolDraftTextExtractor().feed(payload)

        # Assert
        self.assertEqual(text, "prose")

    def test_malformed_input_never_raises(self):
        # Arrange
        extractor = ToolDraftTextExtractor()

        # Act
        text = extractor.feed(']}{"": \\u12 "x" [[')

        # Assert: best-effort silence, not an exception.
        self.assertIsInstance(text, str)

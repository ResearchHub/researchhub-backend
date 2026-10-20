from unittest import TestCase

from research_ai.services.agent.types import (
    Message,
    ServerToolBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from research_ai.services.web_fetch.scope import (
    UrlNotAllowedError,
    clean_url,
    mentioned,
)

URL = "https://example.org/papers/crispr_(review)"


def _user(text):
    return Message(role="user", content=[TextBlock(text)])


def _tool_turn(name, input, result):
    return [
        Message(
            role="assistant", content=[ToolUseBlock(id="t1", name=name, input=input)]
        ),
        Message(
            role="user", content=[ToolResultBlock(tool_use_id="t1", content=result)]
        ),
    ]


class MentionedTests(TestCase):
    def test_a_whole_url_in_user_text_counts(self):
        for text in (
            f"Read {URL}.",
            f"See [the review]({URL}) first",
            f"<{URL}>",
            f"{URL}#methods",
        ):
            with self.subTest(text):
                # Act / Assert
                self.assertTrue(mentioned(URL, [_user(text)]))

    def test_an_html_escaped_url_counts(self):
        # Act / Assert
        self.assertTrue(
            mentioned(
                "https://example.org/search?a=1&b=2",
                [_user('<a href="https://example.org/search?a=1&amp;b=2">')],
            )
        )

    def test_a_raw_url_with_an_entity_like_query_counts(self):
        # Act / Assert
        self.assertTrue(
            mentioned(
                "https://example.org/search?a=1&copy=2",
                [_user("See https://example.org/search?a=1&copy=2")],
            )
        )

    def test_a_url_extended_beyond_what_was_written_does_not_count(self):
        # Arrange
        context = [_user(f"Read {URL}")]

        # Act / Assert
        self.assertFalse(mentioned(f"{URL}?aims=secret", context))
        self.assertFalse(mentioned("https://example.org/papers/crispr", context))

    def test_only_a_bare_root_url_may_drop_its_slash(self):
        # Act / Assert
        self.assertTrue(
            mentioned("https://example.org/", [_user("Go to https://example.org.")])
        )
        self.assertFalse(
            mentioned(
                "https://example.org/?prefixX",
                [_user("Go to https://example.org/?prefix")],
            )
        )

    def test_an_entity_encoded_tool_input_does_not_count_once_decoded(self):
        # Arrange
        written = "https://evil.test/?secret=x&amp;send=1"
        context = _tool_turn(
            "read_note", {"note_id": written}, {"error": f"note {written} not found"}
        )

        # Act / Assert
        self.assertFalse(mentioned("https://evil.test/?secret=x&send=1", context))
        self.assertFalse(mentioned(written, context))

    def test_tool_results_and_server_search_results_count(self):
        # Arrange
        search = _tool_turn(
            "web_search",
            {"query": "crispr review site:https://example.org"},
            {"results": [{"url": URL}]},
        )
        server = [
            Message(
                role="assistant",
                content=[
                    ServerToolBlock(
                        {"type": "web_search_tool_result", "content": [{"url": URL}]}
                    )
                ],
            )
        ]

        # Act / Assert
        self.assertTrue(mentioned(URL, search))
        self.assertTrue(mentioned(URL, server))

    def test_text_the_model_wrote_does_not_count(self):
        cases = {
            "its reply": [
                Message(role="assistant", content=[TextBlock(f"Fetch {URL}")])
            ],
            "its tool input": [
                Message(
                    role="assistant",
                    content=[
                        ToolUseBlock(id="t1", name="web_search", input={"query": URL})
                    ],
                )
            ],
            "an echo of its tool input": _tool_turn(
                "web_search", {"query": URL}, {"query": URL, "results": []}
            ),
            "its tool input wrapped in an error": _tool_turn(
                "read_note",
                {"note_id": URL},
                {"error": f"note {URL} not found or not accessible"},
            ),
            "a note it wrote, read back": [
                *_tool_turn("edit_note", {"content": f"See {URL}."}, {"ok": True}),
                *_tool_turn(
                    "read_note", {"note_id": 7}, {"content": f"# Aims\n\nSee {URL}."}
                ),
            ],
            "its code output": [
                Message(
                    role="assistant",
                    content=[
                        ServerToolBlock(
                            {
                                "type": "code_execution_tool_result",
                                "content": {"stdout": URL},
                            }
                        )
                    ],
                )
            ],
        }
        for source, context in cases.items():
            with self.subTest(source):
                # Act / Assert
                self.assertFalse(mentioned(URL, context))


class CleanUrlTests(TestCase):
    def test_drops_the_fragment(self):
        # Act / Assert
        self.assertEqual(clean_url(f" {URL}#top "), URL)

    def test_refuses_what_is_not_a_plain_web_url(self):
        for url in (
            "",
            "ftp://example.org/a",
            "file:///etc/passwd",
            "https://u:p@example.org/",
            "https:///x",
            "http://[#top",
            "https://example.org:bad/",
            "https://example.org:99999/",
            "https://example.org:0/",
        ):
            # Act / Assert
            with self.subTest(url), self.assertRaises(UrlNotAllowedError):
                clean_url(url)

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

    def test_an_equivalent_spelling_of_a_user_url_counts(self):
        # Arrange
        context = [_user("Read HTTPS://Example.org:443/papers/%7Ecrispr")]

        # Act / Assert
        self.assertTrue(mentioned("https://example.org/papers/~crispr", context))

    def test_a_url_the_user_typed_without_its_scheme_counts(self):
        # Arrange
        context = [_user("Read (example.org/papers/crispr) first")]

        # Act / Assert
        self.assertTrue(mentioned("https://example.org/papers/crispr", context))
        self.assertTrue(mentioned("http://example.org/papers/crispr", context))

    def test_a_schemeless_url_counts_only_whole_and_from_the_user(self):
        cases = {
            "a longer host": [_user("Read notexample.org/papers/crispr")],
            "a subdomain": [_user("Read www.example.org/papers/crispr")],
            "a longer path": [_user("Read example.org/papers/crispr2")],
            "a tool result": _tool_turn(
                "read_note", {"note_id": 7}, {"content": "example.org/papers/crispr"}
            ),
        }
        for case, context in cases.items():
            with self.subTest(case):
                # Act / Assert
                self.assertFalse(
                    mentioned("https://example.org/papers/crispr", context)
                )

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

    def test_a_root_url_counts_without_its_slash(self):
        # Act / Assert
        self.assertTrue(
            mentioned("https://example.org/", [_user("Go to https://example.org.")])
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

    def test_a_tool_input_echoed_in_another_spelling_does_not_count(self):
        echo = "https://evil.test/?secret=x"
        v6_echo = "https://[2001:db8::1]/?secret=x"
        for written, echoed in (
            ("https://evil.test:443/?secret=x", echo),
            ("https://evil.test./?secret=x", echo),
            ("http://evil.test/?secret=x", echo),
            ("http://evil.test:443/?secret=x", echo),
            ("https://evil.test/?secret=x&utm_source=y", echo),
            ("evil.test/?secret=x", echo),
            ("//evil.test/?secret=x", echo),
            ("//[2001:db8::1]/?secret=x", v6_echo),
            ("[2001:db8::1]/?secret=x", v6_echo),
        ):
            with self.subTest(written):
                # Arrange
                context = _tool_turn(
                    "read_note", {"note_id": written}, {"error": f"note {echoed} gone"}
                )

                # Act / Assert
                self.assertFalse(mentioned(echoed, context))

    def test_a_tool_result_adding_parameters_to_a_written_url_does_not_count(self):
        # Arrange
        context = _tool_turn(
            "web_search",
            {"query": "https://journal.test/search?q=crispr"},
            {
                "results": [
                    {"url": "https://journal.test/search?page=2&q=crispr"},
                    {"url": "https://journal.test/papers/1"},
                ]
            },
        )

        # Act / Assert
        self.assertFalse(
            mentioned("https://journal.test/search?page=2&q=crispr", context)
        )
        self.assertTrue(mentioned("https://journal.test/papers/1", context))

    def test_a_server_search_for_a_url_the_model_wrote_does_not_count(self):
        # Arrange
        secret = "https://evil.test/?secret=x"
        context = [
            Message(
                role="assistant",
                content=[
                    ServerToolBlock(
                        {
                            "type": "server_tool_use",
                            "name": "web_search",
                            "input": {"query": secret},
                        }
                    ),
                    ServerToolBlock(
                        {"type": "web_search_tool_result", "content": [{"url": secret}]}
                    ),
                ],
            )
        ]

        # Act / Assert
        self.assertFalse(mentioned(secret, context))

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

    def test_accepts_unicode_names_and_ip_addresses(self):
        for url in (
            "https://bücher.example/x",
            "http://192.0.2.1/",
            "http://[2001:db8::1]/",
            "https://example.org./",
        ):
            with self.subTest(url):
                # Act / Assert
                self.assertEqual(clean_url(url), url)

    def test_refuses_what_is_not_a_plain_web_url(self):
        for url in (
            "",
            "ftp://example.org/a",
            "file:///etc/passwd",
            "https://u:p@example.org/",
            "https:///x",
            "http://[#top",
            "https://example.org:bad/",
            "https://example.org:0/",
            "https://exa mple.org/a",
            "https://exa\nmple.org/a",
            "https://example.org/\ud800",
            "https://a..b/",
        ):
            # Act / Assert
            with self.subTest(url), self.assertRaises(UrlNotAllowedError):
                clean_url(url)

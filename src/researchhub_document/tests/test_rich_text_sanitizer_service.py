"""Rich text sanitizer tests.

``fixtures/rich_text_editor_output.json`` holds a document covering every block
and mark of the web block editor, with the HTML each block serializes to. It was
produced by running the editor's own extensions (``components/Editor/extensions``
at web ``origin/main``, TipTap 3.29.2) over that document, so the round-trip tests
below check real editor output rather than hand-written approximations.
"""

import copy
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from researchhub_document.services.rich_text_sanitizer_service import (
    sanitize_editor_document,
    sanitize_html,
)

EDITOR_OUTPUT = json.loads(
    (Path(__file__).parent / "fixtures" / "rich_text_editor_output.json").read_text()
)
URL_ATTRIBUTES = {"action", "cite", "formaction", "href", "poster", "src", "url"}
SAFE_URL = re.compile(r"(?:https?:|mailto:|data:image/(?:png|jpeg|gif|webp)|[/#?]|$)")
UNSAFE_LINKS = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "JAVASCRIPT:alert(1)",
    " javascript:alert(1)",
    "\tjavascript:alert(1)",
    "\njavascript:alert(1)",
    "\x01javascript:alert(1)",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "java\r\nscript:alert(1)",
    "&#106;avascript:alert(1)",
    "javascript&colon;alert(1)",
    "vbscript:msgbox(1)",
    "data:text/html,<script>alert(1)</script>",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "file:///etc/passwd",
]
SAFE_LINKS = [
    "https://www.researchhub.com/paper/1?a=1&b=2#c",
    "http://example.org/",
    "mailto:someone@example.org",
    "/paper/1/title",
    "#section-2",
    "//example.org/path",
]


class _Element:
    def __init__(self, tag, attributes):
        self.tag = tag
        self.attributes = dict(attributes)


class _ElementCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append(_Element(tag, attrs))


def parse_elements(markup):
    collector = _ElementCollector()
    collector.feed(markup)
    collector.close()
    return collector.elements


class ActiveContentAssertions:
    def assert_no_active_content(self, markup):
        for element in parse_elements(markup):
            self.assertNotIn(
                element.tag,
                {"script", "style", "svg", "math", "object", "embed", "base", "form"},
            )
            for name, value in element.attributes.items():
                self.assertFalse(name.startswith("on"), f"{name} kept in {markup}")
                self.assertNotEqual(name, "srcdoc")
                if name in URL_ATTRIBUTES and value:
                    compact = re.sub(r"[\x00-\x20]", "", value).lower()
                    self.assertRegex(compact, SAFE_URL)
            if element.tag == "iframe" and element.attributes.get("src"):
                self.assertTrue(
                    element.attributes["src"].startswith(
                        "https://www.youtube.com/embed/"
                    ),
                    markup,
                )


class SanitizeHtmlLegitimateContentTests(unittest.TestCase):
    def test_every_editor_block_round_trips_unchanged(self):
        for block in EDITOR_OUTPUT["blocks"]:
            with self.subTest(node=block["node"]):
                # Act
                cleaned = sanitize_html(block["html"])

                # Assert
                self.assertEqual(cleaned, block["html"])

    def test_whole_editor_document_round_trips_unchanged(self):
        # Arrange
        document = "".join(block["html"] for block in EDITOR_OUTPUT["blocks"])

        # Act
        cleaned = sanitize_html(document)

        # Assert
        self.assertEqual(cleaned, document)

    def test_fixture_covers_the_editor_features_the_allow_list_supports(self):
        # Arrange
        document = "".join(block["html"] for block in EDITOR_OUTPUT["blocks"])
        tags = {element.tag for element in parse_elements(document)}

        # Assert
        self.assertLessEqual(
            {"figure", "figcaption", "img", "table", "iframe", "pre", "a", "input"},
            tags,
        )
        self.assertIn('data-type="inline-math"', document)
        self.assertIn('data-type="block-math"', document)

    def test_legacy_ckeditor_markup_round_trips_unchanged(self):
        documents = [
            '<figure class="image image_resized image-style-align-center" '
            'style="width:50%;"><img src="https://example.org/a.png" alt="">'
            "<figcaption>Figure 1</figcaption></figure>",
            '<figure class="table"><table><thead><tr><th>A</th></tr></thead>'
            "<tbody><tr><td>1</td></tr></tbody></table></figure>",
            '<figure class="media"><oembed url="https://youtu.be/abc"></oembed>'
            "</figure>",
            '<p><span class="math-tex">\\(x^2\\)</span> and <del>old</del></p>',
            '<blockquote cite="https://example.org/"><p>Quote</p></blockquote>',
        ]
        for document in documents:
            with self.subTest(document=document):
                self.assertEqual(sanitize_html(document), document)

    def test_inline_raster_image_is_kept(self):
        # Arrange
        document = '<img src="data:image/png;base64,iVBORw0KGgo=" alt="plot">'

        # Act
        cleaned = sanitize_html(document)

        # Assert
        self.assertEqual(cleaned, document)

    def test_text_without_markup_is_returned_unchanged(self):
        for text in (
            "",
            "plain body",
            "a > b & c",
            "# Title\n\n> quote\n",
            "&lt;b&gt;",
        ):
            with self.subTest(text=text):
                self.assertEqual(sanitize_html(text), text)

    def test_non_string_input_is_returned_unchanged(self):
        self.assertIsNone(sanitize_html(None))
        self.assertEqual(sanitize_html(5), 5)

    def test_escaped_markup_in_text_stays_escaped(self):
        # Arrange
        document = "<p>Use &lt;script&gt; tags &amp; p &lt; 0.05</p>"

        # Act
        cleaned = sanitize_html(document)

        # Assert
        self.assertEqual(cleaned, document)

    def test_cleaning_is_idempotent(self):
        # Arrange
        hostile = '<p onclick="x">a</p><img src=x onerror=y><figure><b>c</b></figure>'

        # Act
        once = sanitize_html(hostile)

        # Assert
        self.assertEqual(sanitize_html(once), once)


class SanitizeHtmlHostileContentTests(ActiveContentAssertions, unittest.TestCase):
    def assert_neutralised(self, payloads):
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assert_no_active_content(sanitize_html(payload))

    def test_event_handler_attributes_are_removed(self):
        self.assert_neutralised(
            [
                "<img src=x onerror=alert(1)>",
                "<IMG SRC=x OnErRoR=alert(1)>",
                "<img/src=x/onerror=alert(1)>",
                '<p onclick="alert(1)">text</p>',
                '<a href="https://example.org" onmouseover="alert(1)">x</a>',
                "<details open ontoggle=alert(1)>x</details>",
                "<video src=x onerror=alert(1)></video>",
                "<table onpointerenter=alert(1)><tr><td onclick=x>c</td></tr></table>",
                "<input onfocus=alert(1) autofocus>",
                "<div onanimationstart=alert(1) style=animation-name:x>d</div>",
            ]
        )

    def test_handler_is_removed_and_surrounding_content_is_kept(self):
        # Act
        cleaned = sanitize_html('<p class="lead" onclick="alert(1)">Results</p>')

        # Assert
        self.assertEqual(cleaned, '<p class="lead">Results</p>')

    def test_script_tags_are_removed_with_their_content(self):
        for payload in (
            "<script>alert(1)</script>",
            "<SCRIPT SRC=https://evil.example/x.js></SCRIPT>",
            "<script\n>alert(1)</script\n>",
            "<scr<script>ipt>alert(1)</scr</script>ipt>",
        ):
            with self.subTest(payload=payload):
                # Act
                cleaned = sanitize_html(f"<p>before</p>{payload}")

                # Assert
                self.assert_no_active_content(cleaned)
                self.assertTrue(cleaned.startswith("<p>before</p>"))

    def test_script_body_is_not_left_behind_as_text(self):
        # Act
        cleaned = sanitize_html("<p>a</p><script>steal(document.cookie)</script>")

        # Assert
        self.assertEqual(cleaned, "<p>a</p>")

    def test_unsafe_link_targets_are_removed_and_text_is_kept(self):
        for href in UNSAFE_LINKS:
            with self.subTest(href=href):
                # Arrange
                escaped = href.replace('"', "&quot;").replace("<", "&lt;")

                # Act
                cleaned = sanitize_html(f'<a href="{escaped}">label</a>')

                # Assert
                self.assertEqual(cleaned, "<a>label</a>")

    def test_allowed_link_targets_are_kept(self):
        for href in SAFE_LINKS:
            with self.subTest(href=href):
                # Arrange
                escaped = href.replace("&", "&amp;")
                document = f'<a href="{escaped}">label</a>'

                # Act
                cleaned = sanitize_html(document)

                # Assert
                self.assertEqual(cleaned, document)

    def test_hostile_figure_content_is_neutralised(self):
        self.assert_neutralised(
            [
                "<figure><img src=x onerror=alert(1)></figure>",
                "<figure><script>alert(1)</script></figure>",
                "<figure><svg onload=alert(1)></svg></figure>",
                "<figure><figcaption onclick=alert(1)>c</figcaption></figure>",
                '<figure><a href="javascript:alert(1)">x</a></figure>',
                '<figure class="image"><iframe src="javascript:alert(1)"></iframe>'
                "</figure>",
                '<figure onmouseover="alert(1)"><img src="https://a.example/b.png">'
                "</figure>",
            ]
        )

    def test_figure_keeps_safe_content_when_hostile_content_is_removed(self):
        # Act
        cleaned = sanitize_html(
            '<figure class="image"><img src="https://a.example/b.png" '
            "onerror=alert(1)><figcaption>Caption</figcaption></figure>"
        )

        # Assert
        self.assertEqual(
            cleaned,
            '<figure class="image"><img src="https://a.example/b.png">'
            "<figcaption>Caption</figcaption></figure>",
        )

    def test_stored_figure_source_attribute_is_cleaned(self):
        # Arrange
        document = (
            '<figure data-original-content="&lt;img src=x onerror=alert(1)&gt;'
            '&lt;script&gt;alert(2)&lt;/script&gt;"></figure>'
        )

        # Act
        cleaned = sanitize_html(document)
        figure = parse_elements(cleaned)[0]

        # Assert
        self.assert_no_active_content(figure.attributes["data-original-content"])
        self.assertIn("<img", figure.attributes["data-original-content"])

    def test_only_youtube_embeds_can_be_framed(self):
        self.assert_neutralised(
            [
                '<iframe src="javascript:alert(1)"></iframe>',
                '<iframe src="https://evil.example/embed/x"></iframe>',
                '<iframe src="https://www.youtube.com.evil.example/embed/x"></iframe>',
                '<iframe src="https://www.youtube.com@evil.example/embed/x"></iframe>',
                '<iframe src="https://www.youtube.com\\@evil.example/embed/x"></iframe>',
                '<iframe src="http://www.youtube.com/embed/x"></iframe>',
                '<iframe src="https://www.youtube.com/redirect?q=x"></iframe>',
                '<iframe src="https://www.youtube.com/embed/../redirect"></iframe>',
                '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
            ]
        )

    def test_youtube_embed_cannot_carry_markup_or_extra_capabilities(self):
        # Act
        cleaned = sanitize_html(
            '<iframe src="https://www.youtube.com/embed/x" '
            'srcdoc="<script>alert(1)</script>" allow="camera" sandbox="">'
            "<img src=x onerror=alert(1)></iframe>"
        )

        # Assert
        self.assertEqual(
            cleaned, '<iframe src="https://www.youtube.com/embed/x"></iframe>'
        )

    def test_elements_that_change_parsing_or_load_code_are_removed(self):
        self.assert_neutralised(
            [
                "<svg onload=alert(1)><script>alert(1)</script></svg>",
                "<svg><a xlink:href=javascript:alert(1)><text>x</text></a></svg>",
                "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
                '<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
                "<xmp><img src=x onerror=alert(1)></xmp>",
                "<title><img src=x onerror=alert(1)></title>",
                "<textarea><img src=x onerror=alert(1)></textarea>",
                "<template><img src=x onerror=alert(1)></template>",
                "<object data=javascript:alert(1)></object>",
                "<embed src=javascript:alert(1)>",
                "<form action=javascript:alert(1)><button>b</button></form>",
                "<button formaction=javascript:alert(1)>b</button>",
                '<base href="https://evil.example/">',
                '<meta http-equiv="refresh" content="0;url=https://evil.example">',
                '<link rel="stylesheet" href="https://evil.example/x.css">',
                "<!--<img src=x onerror=alert(1)>-->",
                "<style>@import 'https://evil.example/x.css';</style>",
            ]
        )

    def test_unsafe_media_urls_are_removed(self):
        self.assert_neutralised(
            [
                '<img src="javascript:alert(1)">',
                '<img src="data:image/svg+xml,<svg onload=alert(1)>">',
                '<img src="data:text/html,<script>alert(1)</script>">',
                '<img srcset="javascript:alert(1) 1x">',
                '<video poster="javascript:alert(1)"></video>',
                '<video><source src="javascript:alert(1)"></video>',
                '<oembed url="javascript:alert(1)"></oembed>',
                '<blockquote cite="javascript:alert(1)">q</blockquote>',
            ]
        )
        self.assertEqual(
            sanitize_html('<img srcset="javascript:alert(1) 1x">'),
            "<img>",
        )

    def test_inputs_are_always_inert_checkboxes(self):
        for payload in (
            '<input type="image" src="https://evil.example/x.png">',
            '<input type="password" name="password">',
            '<input type="submit" formaction="https://evil.example/">',
            "<input>",
        ):
            with self.subTest(payload=payload):
                self.assertEqual(sanitize_html(payload), '<input type="checkbox">')

    def test_unsafe_style_declarations_are_removed(self):
        cases = {
            '<p style="color: red; position: fixed; inset: 0">t</p>': (
                '<p style="color: red;">t</p>'
            ),
            '<p style="background: url(javascript:alert(1))">t</p>': "<p>t</p>",
            '<p style="color: expression(alert(1))">t</p>': "<p>t</p>",
            '<p style="width: 1px; -moz-binding: url(x)">t</p>': (
                '<p style="width: 1px;">t</p>'
            ),
            '<p style="color: r\\65 d">t</p>': "<p>t</p>",
            '<p style="/*;*/position: fixed">t</p>': "<p>t</p>",
        }
        for payload, expected in cases.items():
            with self.subTest(payload=payload):
                self.assertEqual(sanitize_html(payload), expected)


class SanitizeEditorDocumentLegitimateContentTests(unittest.TestCase):
    comment_document = {
        "type": "doc",
        "content": [
            {
                "type": "sectionHeader",
                "attrs": {
                    "sectionId": "overall",
                    "title": "Overall",
                    "description": None,
                    "rating": 4,
                },
            },
            {"type": "heading", "attrs": {"level": 2}, "content": []},
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "mention",
                        "attrs": {
                            "id": "12",
                            "userId": "12",
                            "authorProfileId": "9",
                            "label": "A Researcher",
                            "displayName": "A Researcher",
                            "entityType": "user",
                            "mentionSuggestionChar": "@",
                            "doi": None,
                        },
                    },
                    {"type": "text", "text": " see <b>this</b> & "},
                    {
                        "type": "text",
                        "text": "paper",
                        "marks": [
                            {"type": "bold"},
                            {
                                "type": "link",
                                "attrs": {
                                    "href": "https://doi.org/10.1000/1",
                                    "target": "_blank",
                                    "rel": "noopener noreferrer nofollow",
                                    "class": None,
                                    "title": None,
                                    "noRichPreview": False,
                                },
                            },
                        ],
                    },
                    {
                        "type": "richLink",
                        "attrs": {
                            "url": "https://www.youtube.com/watch?v=abc",
                            "kind": "youtube",
                            "videoId": "abc",
                            "tweetId": None,
                            "linkedinUrn": None,
                        },
                    },
                ],
            },
            {
                "type": "image",
                "attrs": {
                    "src": "https://storage.example/uploads/comments/users/1/a.png",
                    "alt": "plot",
                    "title": None,
                    "width": 320,
                    "height": 200,
                },
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "html"},
                "content": [{"type": "text", "text": "<script>alert(1)</script>"}],
            },
        ],
    }

    def test_block_editor_document_is_returned_unchanged(self):
        # Arrange
        document = copy.deepcopy(EDITOR_OUTPUT["document"])

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertIs(cleaned, document)
        self.assertEqual(document, EDITOR_OUTPUT["document"])

    def test_json_string_is_returned_byte_for_byte(self):
        # Arrange
        document = json.dumps(EDITOR_OUTPUT["document"], indent=1, sort_keys=True)

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertIs(cleaned, document)

    def test_comment_document_is_returned_unchanged(self):
        # Arrange
        document = copy.deepcopy(self.comment_document)

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(cleaned, self.comment_document)

    def test_quill_document_is_returned_unchanged(self):
        # Arrange
        document = {
            "ops": [
                {"insert": "Dose < 20µM ", "attributes": {"bold": True}},
                {"insert": "link", "attributes": {"link": "https://example.org"}},
                {"insert": {"image": "https://example.org/a.png"}},
                {"insert": {"image": "data:image/png;base64,iVBORw0KGgo="}},
                {"insert": {"video": "https://www.youtube.com/embed/x"}},
                {"insert": {"user": {"id": 1, "first_name": "A"}}},
                {"insert": "\n", "attributes": {"list": "ordered"}},
            ]
        }
        expected = copy.deepcopy(document)

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(cleaned, expected)

    def test_document_metadata_is_kept(self):
        # Arrange
        document = {
            "type": "doc",
            "attrs": {
                "registered_report_prefill": {
                    "proposal_id": 4,
                    "image": "uploads/posts/users/1/a/cover.png",
                }
            },
            "content": [],
        }
        expected = copy.deepcopy(document)

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(cleaned, expected)

    def test_empty_values_are_returned_unchanged(self):
        for value in (None, "", {}, [], 0):
            with self.subTest(value=value):
                self.assertEqual(sanitize_editor_document(value), value)

    def test_safe_link_marks_are_kept(self):
        for href in SAFE_LINKS:
            with self.subTest(href=href):
                # Arrange
                document = _document_with_link(href)

                # Act
                cleaned = sanitize_editor_document(document)

                # Assert
                self.assertIs(cleaned, document)


class SanitizeEditorDocumentHostileContentTests(
    ActiveContentAssertions, unittest.TestCase
):
    def test_unsafe_link_marks_are_removed_and_text_is_kept(self):
        for href in [*UNSAFE_LINKS, 5, ["javascript:alert(1)"]]:
            with self.subTest(href=href):
                # Arrange
                document = _document_with_link(href)

                # Act
                cleaned = sanitize_editor_document(document)

                # Assert
                text_node = cleaned["content"][0]["content"][0]
                self.assertEqual(text_node["text"], "label")
                self.assertEqual(text_node["marks"], [{"type": "bold"}])

    def test_string_documents_are_cleaned_and_stay_strings(self):
        # Arrange
        document = json.dumps(_document_with_link("javascript:alert(1)"))

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertIsInstance(cleaned, str)
        self.assertNotIn("javascript:", cleaned)
        self.assertEqual(json.loads(cleaned)["content"][0]["type"], "paragraph")

    def test_wrapped_comment_documents_are_cleaned(self):
        for wrap in (
            lambda doc: {"content": doc},
            lambda doc: {"type": "doc", "content": [{"content": doc}]},
            lambda doc: {"content": doc["content"]},
        ):
            # Arrange
            document = wrap(_document_with_link("javascript:alert(1)"))

            # Act
            cleaned = sanitize_editor_document(document)

            # Assert
            self.assertNotIn("javascript:", json.dumps(cleaned))

    def test_event_handler_and_raw_html_attributes_are_removed(self):
        # Arrange
        document = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {
                        "id": "p-1",
                        "onclick": "alert(1)",
                        "ONMOUSEOVER": "alert(1)",
                        "srcdoc": "<script>alert(1)</script>",
                        "innerHTML": "<img src=x onerror=alert(1)>",
                        "outerHTML": "<script>alert(1)</script>",
                        "dangerouslySetInnerHTML": {"__html": "<script></script>"},
                        "html": "<script>alert(1)</script>",
                    },
                }
            ],
        }

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(cleaned["content"][0]["attrs"], {"id": "p-1"})

    def test_mark_attributes_are_cleaned(self):
        # Arrange
        document = {
            "type": "text",
            "text": "x",
            "marks": [{"type": "textStyle", "attrs": {"onclick": "alert(1)"}}],
        }

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(cleaned["marks"], [{"type": "textStyle", "attrs": {}}])

    def test_unsafe_media_and_rich_link_urls_are_blanked(self):
        cases = [
            ("imageBlock", "src", "javascript:alert(1)"),
            ("image", "src", "data:image/svg+xml,<svg onload=alert(1)>"),
            ("image", "src", "data:text/html,<script>alert(1)</script>"),
            ("youtube", "src", " JaVaScRiPt:alert(1)"),
            ("richLink", "url", "java\tscript:alert(1)"),
            ("embed", "url", "vbscript:x"),
        ]
        for node_type, attribute, url in cases:
            with self.subTest(node_type=node_type, url=url):
                # Arrange
                document = {
                    "type": "doc",
                    "content": [{"type": node_type, "attrs": {attribute: url}}],
                }

                # Act
                cleaned = sanitize_editor_document(document)

                # Assert
                self.assertEqual(cleaned["content"][0]["attrs"], {attribute: ""})

    def test_figure_source_is_sanitized_and_safe_markup_is_kept(self):
        # Arrange
        document = {
            "type": "doc",
            "content": [
                {
                    "type": "figure",
                    "attrs": {
                        "class": "image",
                        "originalContent": (
                            '<img src="https://a.example/b.png" onerror="alert(1)">'
                            "<script>alert(2)</script>"
                            "<figcaption onclick=x>Caption</figcaption>"
                        ),
                    },
                }
            ],
        }

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(
            cleaned["content"][0]["attrs"]["originalContent"],
            '<img src="https://a.example/b.png"><figcaption>Caption</figcaption>',
        )

    def test_non_string_figure_source_is_cleared(self):
        # Arrange
        document = {"type": "figure", "attrs": {"originalContent": {"a": 1}}}

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(cleaned["attrs"]["originalContent"], "")

    def test_style_attributes_are_filtered(self):
        # Arrange
        document = {
            "type": "tableCell",
            "attrs": {"style": "color: red; position: fixed", "colspan": 1},
            "content": [
                {
                    "type": "text",
                    "text": "x",
                    "marks": [
                        {
                            "type": "textStyle",
                            "attrs": {
                                "color": "red; position: fixed",
                                "fontFamily": "Georgia, serif",
                                "fontSize": "url(https://evil.example/)",
                            },
                        }
                    ],
                }
            ],
        }

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(cleaned["attrs"], {"style": "color: red;", "colspan": 1})
        self.assertEqual(
            cleaned["content"][0]["marks"][0]["attrs"],
            {"fontFamily": "Georgia, serif"},
        )

    def test_quill_links_and_embeds_are_cleaned(self):
        # Arrange
        document = {
            "ops": [
                {"insert": "a", "attributes": {"link": "javascript:alert(1)"}},
                {"insert": {"image": "javascript:alert(1)"}},
                {"insert": {"video": "JAVASCRIPT:alert(1)"}},
            ]
        }

        # Act
        cleaned = sanitize_editor_document(document)

        # Assert
        self.assertEqual(
            cleaned["ops"],
            [
                {"insert": "a", "attributes": {}},
                {"insert": {"image": ""}},
                {"insert": {"video": ""}},
            ],
        )

    def test_text_that_is_not_json_is_cleaned_as_html(self):
        # Act
        cleaned = sanitize_editor_document("<p onclick=alert(1)>body</p>")

        # Assert
        self.assertEqual(cleaned, "<p>body</p>")

    def test_document_too_deep_to_inspect_is_dropped(self):
        # Arrange
        as_string = '{"content":[' * 100_000 + "]}" * 100_000
        as_object = current = {}
        for _ in range(100_000):
            current["content"] = [{}]
            current = current["content"][0]

        # Act / Assert
        self.assertIsNone(sanitize_editor_document(as_string))
        self.assertIsNone(sanitize_editor_document(as_object))


def _document_with_link(href):
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "label",
                        "marks": [
                            {"type": "bold"},
                            {"type": "link", "attrs": {"href": href}},
                        ],
                    }
                ],
            }
        ],
    }

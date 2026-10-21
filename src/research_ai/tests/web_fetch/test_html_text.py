from unittest import TestCase

from research_ai.services.web_fetch.html_text import (
    html_to_markdown,
    looks_like_challenge,
)

BODY = "Single-cell CRISPR screens map enhancer activity across 40 donors. " * 5
HTML = (
    "<html><head><title> CRISPR\n screens </title><script>track()</script></head>"
    f"<body><nav>Home</nav><main><h1>Results</h1><p>{BODY}</p>"
    '<a href="/supplement" title="Supplementary data">Supplement</a></main>'
    "<footer>Cookies</footer></body></html>"
).encode()


class HtmlToMarkdownTests(TestCase):
    def test_keeps_the_main_content_with_absolute_links(self):
        # Act
        title, text = html_to_markdown(
            HTML, base_url="https://journal.example.org/articles/a", encoding="utf-8"
        )

        # Assert
        self.assertEqual(title, "CRISPR screens")
        self.assertTrue(text.startswith("# Results"))
        self.assertIn("[Supplement](https://journal.example.org/supplement)", text)
        for dropped in ("track()", "Home", "Cookies", "Supplementary data"):
            self.assertNotIn(dropped, text)

    def test_a_small_main_element_is_not_taken_for_the_page(self):
        # Arrange
        page = f"<body><main>Menu</main><div><p>{BODY}</p></div></body>".encode()

        # Act
        _, text = html_to_markdown(page, base_url="https://example.org/", encoding=None)

        # Assert
        self.assertIn(BODY.strip(), text)

    def test_links_resolve_against_the_document_base(self):
        # Arrange
        page = (
            '<head><base href="https://cdn.example.org/docs/"></head>'
            f'<body><p>{BODY}</p><a href="chapter">Chapter</a></body>'
        ).encode()

        # Act
        _, text = html_to_markdown(
            page, base_url="https://example.org/a/page", encoding=None
        )

        # Assert
        self.assertIn("[Chapter](https://cdn.example.org/docs/chapter)", text)

    def test_an_invalid_document_base_is_ignored(self):
        for base in (
            "http:///docs/",
            "https://cdn.example.org:bad/docs/",
            "https://cdn exa.example.org/docs/",
        ):
            with self.subTest(base):
                # Arrange
                page = (
                    f'<head><base href="{base}"></head>'
                    f'<body><p>{BODY}</p><a href="chapter">Chapter</a></body>'
                ).encode()

                # Act
                _, text = html_to_markdown(
                    page, base_url="https://example.org/a/page", encoding=None
                )

                # Assert
                self.assertIn("[Chapter](https://example.org/a/chapter)", text)

    def test_a_malformed_link_keeps_its_text_and_the_page(self):
        # Arrange
        page = f'<body><p>{BODY}</p><a href="http://[">Data</a></body>'.encode()

        # Act
        _, text = html_to_markdown(page, base_url="https://example.org/", encoding=None)

        # Assert
        self.assertIn(BODY.strip(), text)
        self.assertIn("Data", text)
        self.assertNotIn("http://[", text)

    def test_images_keep_absolute_sources_but_not_icons_or_inline_data(self):
        # Arrange
        page = (
            f"<body><p>{BODY}</p>"
            '<figure><img src="/fig/1.png" alt="Figure 1:\n enhancer map" '
            'title="Click to enlarge"></figure>'
            '<img src="/blank.gif" data-src="fig/2.jpg" alt="Figure 2">'
            '<img data-src="" src="fig/4.png" alt="Figure 4">'
            '<img data-src="#lazy" src="fig/5.png" alt="Figure 5">'
            '<table><tr><td><img src="fig/3.png" alt="Figure 3"></td></tr></table>'
            '<img src="/logo.png" width="24" alt="Logo">'
            '<img src="data:image/png;base64,AAAA" alt="Inline">'
            "</body>"
        ).encode()

        # Act
        _, text = html_to_markdown(
            page, base_url="https://example.org/a/page", encoding=None
        )

        # Assert
        self.assertIn("![Figure 1: enhancer map](https://example.org/fig/1.png)", text)
        self.assertIn("![Figure 2](https://example.org/a/fig/2.jpg)", text)
        self.assertIn("![Figure 3](https://example.org/a/fig/3.png)", text)
        self.assertIn("![Figure 4](https://example.org/a/fig/4.png)", text)
        self.assertIn("![Figure 5](https://example.org/a/fig/5.png)", text)
        for dropped in ("Click to enlarge", "Logo", "Inline", "data:", "blank.gif"):
            self.assertNotIn(dropped, text)


class LooksLikeChallengeTests(TestCase):
    def test_spots_an_interstitial_but_not_an_article(self):
        # Act / Assert
        self.assertTrue(looks_like_challenge(b"<title>Just a moment...</title>"))
        self.assertFalse(looks_like_challenge(HTML))

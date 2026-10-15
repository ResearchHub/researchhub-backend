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


class LooksLikeChallengeTests(TestCase):
    def test_spots_an_interstitial_but_not_an_article(self):
        # Act / Assert
        self.assertTrue(looks_like_challenge(b"<title>Just a moment...</title>"))
        self.assertFalse(looks_like_challenge(HTML))

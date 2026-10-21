from unittest import TestCase
from unittest.mock import Mock, patch

import httpx
from django.contrib.auth import get_user_model

from research_ai.models import AgentFile
from research_ai.services.agent.types import Message, TextBlock
from research_ai.services.agent_files.config import AgentFileConfig
from research_ai.services.agent_files.extraction_service import TextExtractionService
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.web_fetch import (
    DIRECT,
    FALLBACK,
    WebFetchConfig,
    WebFetchError,
    WebFetchService,
)
from research_ai.services.web_fetch import service as service_module
from research_ai.services.web_fetch.exa import ExaContents, FallbackError
from research_ai.tests.agent_files.helpers import FakeBucket, pdf_bytes
from researchhub.services.private_storage_service import PrivateStorageService
from utils.safe_http import UnsafeAddressError
from utils.test_helpers import AWSMockTestCase

URL = "https://journal.example.org/articles/crispr-screens"
BODY = "Single-cell CRISPR screens map enhancer activity across 40 donors. " * 5
HTML = (
    "<html><head><title>CRISPR screens</title><script>track()</script></head>"
    f"<body><nav>Home</nav><main><h1>Results</h1><p>{BODY}</p>"
    '<a href="/supplement">Supplement</a></main></body></html>'
).encode()
FALLBACK_TEXT = "# CRISPR screens\n\n" + BODY
CONFIG = WebFetchConfig(
    max_page_bytes=10_000, max_files_per_conversation=2, direct_hosts=("example.org",)
)


def _html(request, status=200, body=HTML, **headers):
    return httpx.Response(
        status,
        headers={"content-type": "text/html; charset=utf-8", **headers},
        content=body,
    )


class WebFetchServiceTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.bucket = FakeBucket(self.mock_aws_client)
        self.user = get_user_model().objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.conversation = AgentConversationService().create(
            user=self.user, workflow="assistant_chat"
        )
        self.context = [Message(role="user", content=[TextBlock(f"Summarize {URL}.")])]
        self.requests = []
        self.respond = _html
        self.fallback = Mock(spec=ExaContents)
        self.fallback.configured = True
        self.fallback.text.return_value = ("CRISPR screens", FALLBACK_TEXT)
        self.service = WebFetchService(
            http=httpx.Client(transport=httpx.MockTransport(self._handle)),
            fallback=self.fallback,
            storage=PrivateStorageService(bucket="private"),
            extraction=TextExtractionService(),
            config=CONFIG,
            file_config=AgentFileConfig(max_text_chars=10_000),
        )

    def _handle(self, request):
        self.requests.append(str(request.url))
        return self.respond(request)

    def _fetch(self, url=URL):
        return self.service.fetch(
            url, conversation=self.conversation, context=self.context
        )

    def test_direct_page_is_stored_as_fetched_with_its_markdown(self):
        # Act
        with self.assertLogs("research_ai.services.web_fetch.service", "INFO") as logs:
            fetched = self._fetch(URL + "#results")

        # Assert
        file = fetched.file
        self.assertEqual(fetched.path, DIRECT)
        self.assertEqual(self.requests, [URL])
        self.assertEqual(file.source, AgentFile.Source.WEB)
        self.assertEqual(file.source_url, URL)
        self.assertEqual(file.filename, "CRISPR screens")
        self.assertEqual(file.status, AgentFile.Status.READY)
        self.assertEqual(file.conversation, self.conversation)
        self.assertIsNone(file.message)
        self.assertEqual(self.bucket.objects[file.storage_key], HTML)
        self.assertEqual(self.bucket.content_types[file.storage_key], "text/html")
        self.assertTrue(
            file.storage_key.startswith(
                f"uploads/research_ai/users/{self.user.id}/web/"
            )
        )
        self.assertTrue(file.text.startswith("# Results"))
        self.assertIn("path=direct host=journal.example.org", logs.output[0])
        self.fallback.text.assert_not_called()

    def test_direct_pdf_is_extracted_like_an_attached_one(self):
        # Arrange
        pdf_url = "https://journal.example.org/articles/crispr-screens.pdf"
        self.context = [Message(role="user", content=[TextBlock(pdf_url)])]
        pdf = pdf_bytes("Specific aims: map enhancers", "Approach: screens")
        self.respond = lambda request: httpx.Response(
            200, headers={"content-type": "application/octet-stream"}, content=pdf
        )

        # Act
        file = self._fetch(pdf_url).file

        # Assert
        self.assertEqual(file.content_type, "application/pdf")
        self.assertEqual(file.page_count, 2)
        self.assertEqual(file.pages_without_text, 0)
        self.assertIn("[Page 2]\nApproach: screens", file.text)
        self.assertEqual(self.bucket.objects[file.storage_key], pdf)
        self.assertTrue(file.storage_key.endswith("/crispr-screens.pdf"))

    def test_redirects_are_followed_to_the_page(self):
        # Arrange
        moved = "https://cdn.example.org/a/crispr"
        self.respond = lambda request: (
            _html(request)
            if str(request.url) == moved
            else httpx.Response(301, headers={"location": moved})
        )

        # Act
        file = self._fetch().file

        # Assert
        self.assertEqual(self.requests, [URL, moved])
        self.assertEqual(file.source_url, URL)
        self.assertIn("(https://cdn.example.org/supplement)", file.text)

    def test_an_unusable_direct_response_falls_back_to_the_fetch_api(self):
        challenge = b"<html><title>Just a moment...</title>" + HTML
        cases = [
            ("blocked (HTTP 403)", lambda r: _html(r, 403)),
            ("blocked (HTTP 429)", lambda r: _html(r, 429)),
            ("bot challenge page", lambda r: _html(r, body=challenge)),
            (
                "no readable text",
                lambda r: _html(r, body=b"<body><div id=app></div></body>"),
            ),
            ("too large", lambda r: _html(r, body=HTML * 100)),
            (
                "unsupported content type image/png",
                lambda r: httpx.Response(
                    200, headers={"content-type": "image/png"}, content=b"png"
                ),
            ),
            (
                "redirected to a URL that cannot be fetched",
                lambda r: httpx.Response(
                    302, headers={"location": "file:///etc/passwd"}
                ),
            ),
            (
                "redirected to a URL that cannot be fetched",
                lambda r: httpx.Response(302, headers={"location": "http://["}),
            ),
            (
                "not an open-access host",
                lambda r: httpx.Response(
                    302, headers={"location": "https://publisher.test/crispr"}
                ),
            ),
            (
                "request failed (ConnectTimeout)",
                Mock(side_effect=httpx.ConnectTimeout("slow")),
            ),
        ]
        for reason, respond in cases:
            with self.subTest(reason):
                # Arrange
                AgentFile.objects.all().delete()
                self.respond = respond

                # Act
                with self.assertLogs(
                    "research_ai.services.web_fetch.service", "INFO"
                ) as logs:
                    fetched = self._fetch()

                # Assert
                file = fetched.file
                self.assertEqual(fetched.path, FALLBACK)
                self.assertEqual(file.source, AgentFile.Source.WEB_TEXT)
                self.assertEqual(file.content_type, "text/markdown")
                self.assertEqual(file.text, FALLBACK_TEXT)
                self.assertEqual(
                    self.bucket.objects[file.storage_key], FALLBACK_TEXT.encode()
                )
                self.assertIn("path=fallback host=journal.example.org", logs.output[-1])
                self.assertIn(f"reason={reason}", logs.output[-1])
                self.fallback.text.assert_called_with(
                    URL, max_chars=10_000, timeout=30.0
                )

    def test_a_redirect_near_the_deadline_gets_only_the_time_left(self):
        # Arrange
        moved = "https://cdn.example.org/a/crispr"
        clock = [100.0]
        timeouts = []

        def respond(request):
            timeouts.append(request.extensions["timeout"])
            if str(request.url) == moved:
                return _html(request)
            clock[0] += 18  # The first hop takes 18 of the 20 seconds.
            return httpx.Response(301, headers={"location": moved})

        self.respond = respond

        # Act
        with patch.object(service_module.time, "monotonic", lambda: clock[0]):
            fetched = self._fetch()

        # Assert
        self.assertEqual(fetched.path, DIRECT)
        self.assertEqual(timeouts[0]["read"], 20.0)
        self.assertEqual(timeouts[0]["connect"], 5.0)
        self.assertEqual(timeouts[1]["read"], 2.0)
        self.assertEqual(timeouts[1]["connect"], 2.0)

    def test_a_host_off_the_direct_list_goes_straight_to_the_fetch_api(self):
        # Arrange
        url = "https://www.science.org/doi/10.1126/science.abc1234"
        self.context = [Message(role="user", content=[TextBlock(url)])]

        # Act
        fetched = self._fetch(url)

        # Assert
        self.assertEqual(fetched.path, FALLBACK)
        self.assertEqual(self.requests, [])
        self.fallback.text.assert_called_once()

    def test_a_private_address_is_refused_without_the_fallback(self):
        # Arrange
        self.respond = Mock(side_effect=UnsafeAddressError("10.0.0.5 is not public"))

        # Act
        with self.assertRaises(WebFetchError) as raised:
            self._fetch()

        # Assert
        self.assertIn("10.0.0.5 is not public", str(raised.exception))
        self.fallback.text.assert_not_called()
        self.assertFalse(AgentFile.objects.exists())

    def test_a_url_the_conversation_does_not_contain_is_refused(self):
        # Arrange
        self.context = [
            Message(role="user", content=[TextBlock(f"Summarize {URL}")]),
            Message(role="assistant", content=[TextBlock(f"{URL}?q=secret aims")]),
        ]

        # Act
        with self.assertRaises(WebFetchError) as raised:
            self._fetch(f"{URL}?q=secret")

        # Assert
        self.assertIn("does not appear in this conversation", str(raised.exception))
        self.assertEqual(self.requests, [])
        self.fallback.text.assert_not_called()

    def test_failure_on_both_paths_names_each_reason(self):
        # Arrange
        self.respond = lambda request: _html(request, 403)
        self.fallback.text.side_effect = FallbackError("fetch service returned no text")

        # Act
        with (
            self.assertLogs("research_ai.services.web_fetch.service", "INFO") as logs,
            self.assertRaises(WebFetchError) as raised,
        ):
            self._fetch()

        # Assert
        self.assertEqual(
            str(raised.exception),
            f"Could not fetch {URL}: blocked (HTTP 403); "
            "fetch service returned no text.",
        )
        self.assertIn("path=failed", logs.output[-1])
        self.assertFalse(AgentFile.objects.exists())
        self.assertEqual(self.bucket.objects, {})

    def test_without_a_fallback_key_a_blocked_page_fails(self):
        # Arrange
        self.respond = lambda request: _html(request, 403)
        self.fallback.configured = False

        # Act
        with self.assertRaises(WebFetchError) as raised:
            self._fetch()

        # Assert
        self.assertEqual(
            str(raised.exception), f"Could not fetch {URL}: blocked (HTTP 403)."
        )
        self.fallback.text.assert_not_called()

    def test_a_url_fetched_earlier_in_the_chat_is_not_fetched_again(self):
        # Arrange
        first = self._fetch().file

        # Act
        again = self._fetch()

        # Assert
        self.assertTrue(again.reused)
        self.assertEqual(again.path, DIRECT)
        self.assertEqual(again.file.id, first.id)
        self.assertEqual(len(self.requests), 1)

    def test_a_chat_fetches_at_most_its_limit_of_pages(self):
        # Arrange
        urls = [f"https://example.org/{n}" for n in range(3)]
        self.context = [Message(role="user", content=[TextBlock(" ".join(urls))])]
        for url in urls[:2]:
            self._fetch(url)

        # Act
        with self.assertRaises(WebFetchError) as raised:
            self._fetch(urls[2])

        # Assert
        self.assertIn("has fetched 2 pages, its limit", str(raised.exception))
        self.assertEqual(len(self.requests), 2)


class DirectHostsTests(TestCase):
    def test_matches_a_listed_host_and_its_subdomains_only(self):
        # Arrange
        config = WebFetchConfig(direct_hosts=("arxiv.org",))

        # Act / Assert
        self.assertTrue(config.allows_direct("https://arxiv.org/pdf/2401.00001"))
        self.assertTrue(config.allows_direct("https://export.arxiv.org/abs/1"))
        self.assertTrue(config.allows_direct("https://ARXIV.org./abs/1"))
        self.assertFalse(config.allows_direct("https://notarxiv.org/abs/1"))
        self.assertFalse(config.allows_direct("https://arxiv.org.evil.test/abs/1"))

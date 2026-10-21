from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from research_ai.services.agent.types import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.notebook_chat.web_fetch_tools import (
    WEB_FETCH,
    WebFetchToolset,
)
from research_ai.services.web_fetch import (
    DIRECT,
    FetchedPage,
    WebFetchConfig,
    WebFetchError,
    WebFetchService,
)
from research_ai.services.web_fetch.scope import mentioned
from research_ai.tests.agent_files.helpers import make_file

URL = "https://journal.example.org/articles/crispr-screens"
TEXT = "Enhancer maps. " * 3000


class WebFetchToolsetTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.conversation = AgentConversationService().create(
            user=user, workflow="assistant_chat"
        )
        self.file = make_file(
            user,
            filename="CRISPR screens",
            content_type="text/html",
            text=TEXT,
            conversation=self.conversation,
            source="WEB",
            source_url=URL,
        )
        self.context = [Message(role="user", content=[TextBlock(URL)])]
        self.service = Mock(spec=WebFetchService)
        self.service.config = WebFetchConfig(max_fetches_per_turn=2)
        self.service.fetch.return_value = FetchedPage(file=self.file, path=DIRECT)
        self.toolset = WebFetchToolset(
            conversation=self.conversation,
            context=lambda: self.context,
            service=self.service,
        )

    def _call(self, args):
        tools = {tool.name: tool for tool in self.toolset.build_tools()}
        return tools[WEB_FETCH].handler(args)

    def test_returns_the_start_of_the_page_and_how_to_read_on(self):
        # Act
        result = self._call({"url": URL, "max_chars": 1000})

        # Assert
        self.service.fetch.assert_called_once_with(
            URL, conversation=self.conversation, context=self.context
        )
        self.assertEqual(result["attachment_id"], self.file.id)
        self.assertEqual(result["url"], URL)
        self.assertEqual(result["title"], "CRISPR screens")
        self.assertEqual(result["kind"], "web page")
        self.assertEqual(result["fetched_via"], DIRECT)
        self.assertEqual(result["total_chars"], len(TEXT))
        self.assertEqual(result["text"], TEXT[: result["end_char"]])
        self.assertEqual(result["next_start_char"], result["end_char"])
        self.assertLessEqual(result["end_char"], 1000)

    def test_a_search_result_url_can_be_fetched_once_the_call_is_recorded(self):
        # Arrange
        self.context = [
            Message(role="user", content=[TextBlock("Find CRISPR screen papers")]),
            Message(
                role="assistant",
                content=[
                    ToolUseBlock(id="t1", name="web_search", input={"query": "crispr"})
                ],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="t1", content={"url": URL})],
            ),
            Message(
                role="assistant",
                content=[ToolUseBlock(id="t2", name=WEB_FETCH, input={"url": URL})],
            ),
        ]

        # Act
        self._call({"url": URL})

        # Assert
        context = self.service.fetch.call_args.kwargs["context"]
        self.assertTrue(mentioned(URL, context))

    def test_a_pdf_points_to_the_pages_tool_when_offered(self):
        # Arrange
        pdf = make_file(
            self.file.user,
            conversation=self.conversation,
            source="WEB",
            source_url=URL,
        )
        self.service.fetch.return_value = FetchedPage(file=pdf, path=DIRECT)
        self.toolset = WebFetchToolset(
            conversation=self.conversation,
            context=lambda: self.context,
            service=self.service,
            pages_tool=True,
        )

        # Act
        result = self._call({"url": URL})

        # Assert
        self.assertEqual(result["kind"], "PDF")
        self.assertIn("view_attachment_pages", result["note"])

    def test_an_image_points_to_the_pages_tool_when_offered(self):
        # Arrange
        image = make_file(
            self.file.user,
            filename="media.cdn.test/fig1.png",
            content_type="image/png",
            text="",
            conversation=self.conversation,
            source="WEB",
            source_url=URL,
        )
        self.service.fetch.return_value = FetchedPage(file=image, path=DIRECT)
        self.toolset = WebFetchToolset(
            conversation=self.conversation,
            context=lambda: self.context,
            service=self.service,
            pages_tool=True,
        )

        # Act
        result = self._call({"url": URL})

        # Assert
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["text"], "")
        self.assertIn("view_attachment_pages, as page 1", result["note"])

    def test_an_out_of_range_max_chars_is_refused_without_a_fetch(self):
        # Act
        result = self._call({"url": URL, "max_chars": 0})

        # Assert
        self.assertIn("max_chars must be between 1", result["error"])
        self.service.fetch.assert_not_called()

    def test_a_failed_fetch_is_an_error_for_the_model(self):
        # Arrange
        self.service.fetch.side_effect = WebFetchError(
            f"Could not fetch {URL}: HTTP 404."
        )

        # Act
        result = self._call({"url": URL})

        # Assert
        self.assertEqual(result, {"error": f"Could not fetch {URL}: HTTP 404."})

    def test_fetches_stop_at_the_turn_budget(self):
        # Arrange
        self._call({"url": URL})
        self._call({"url": URL})

        # Act
        result = self._call({"url": URL})

        # Assert
        self.assertIn("budget exhausted (2 fetches)", result["error"])
        self.assertEqual(self.service.fetch.call_count, 2)

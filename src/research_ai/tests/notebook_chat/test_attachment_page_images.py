from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from note.tests.helpers import create_note
from research_ai.models import AgentFile
from research_ai.prompts._loader import load_template
from research_ai.services.agent import (
    BedrockProvider,
    ClaudePlatformProvider,
    ImageBlock,
    OpenRouterProvider,
    resolve_provider,
)
from research_ai.services.agent.images import image_placeholder
from research_ai.services.agent.model_capabilities import model_capabilities
from research_ai.services.agent.types import TextBlock, ToolResultBlock
from research_ai.services.agent_files import AgentFileService
from research_ai.services.agent_files.delivery import DeliveryConfig
from research_ai.services.agent_files.image_loader import PrivateStorageImageLoader
from research_ai.services.agent_files.page_images import PageImageService
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.agent_persistence.activity import ToolCallEvent
from research_ai.services.notebook_chat import NotebookChatService
from research_ai.services.notebook_chat import service as chat_service
from research_ai.services.notebook_chat.activity import public_activity
from research_ai.services.notebook_chat.attachment_tools import (
    READ_ATTACHMENT,
    SEARCH_ATTACHMENT,
    VIEW_ATTACHMENT_PAGES,
    AttachmentToolset,
)
from research_ai.services.usage_budget.reservation import claim_deadline
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    text_turn,
    tool_turn,
)
from research_ai.tests.agent_files.helpers import (
    FakeBucket,
    FakeRender,
    image_bytes,
    make_file,
)
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument
from utils.test_helpers import AWSMockTestCase

BUCKET = "researchhub-test-private-storage"
SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
    "AWS_PRIVATE_STORAGE_BUCKET_NAME": BUCKET,
}
VISION_MODEL = "claude_platform:claude-sonnet-5"
# The default tier's model.
TEXT_ONLY_MODEL = "openrouter:deepseek/deepseek-v4-flash-0731"
PDF_TEXT = "[Page 1]\nAim 1: map enhancers.\n\n[Page 2]\nFigure 2 shows the screen."
# A PDF of up to two pages is sent as images; a message carries four pages.
DELIVERY = DeliveryConfig(page_images_max_pages=2, page_images_max_per_message=4)
SHOWN = "its pages are also shown as images with this message"
ON_REQUEST = f"view its pages as images with {VIEW_ATTACHMENT_PAGES}"
USE_TOOLS = "read it with read_attachment or find passages with search_attachment"
NO_ROOM = (
    "its pages cannot be shown as images in this chat, which has no room left "
    "for images"
)
NO_ROOM_ERROR = (
    "This chat has no room left for page images, so no more pages can be "
    "shown. Work from the files' text and say so rather than asking again."
)
# What an adapter writes where an image is not sent, up to the image's label.
PLACEHOLDER = image_placeholder(ImageBlock("ref", "image/jpeg", "|")).split("|")[0]


def _user(name="owner"):
    return get_user_model().objects.create_user(
        username=f"{name}@researchhub_test.com",
        password="password",
        email=f"{name}@researchhub_test.com",
    )


def _page(file, page) -> ImageBlock:
    prefix = file.storage_key.rsplit("/", 1)[0]
    return ImageBlock(
        f"{prefix}/pages/{page}.jpg", "image/jpeg", f"{file.filename}, page {page}"
    )


def _shown(file) -> ImageBlock:
    """An uploaded image as a model is shown it."""
    prefix = file.storage_key.rsplit("/", 1)[0]
    return ImageBlock(f"{prefix}/pages/1.jpg", "image/jpeg", file.filename)


def _images(messages) -> list[ImageBlock]:
    """Every image a request carries, sent with a message or in a tool result."""
    images = []
    for message in messages:
        for block in message.content:
            if isinstance(block, ImageBlock):
                images.append(block)
            elif isinstance(block, ToolResultBlock):
                images.extend(block.images)
    return images


class BucketTestCase(AWSMockTestCase):
    """Chat files whose originals sit in a fake private bucket."""

    def setUp(self):
        super().setUp()
        self.user = _user()
        self.bucket = FakeBucket(self.mock_aws_client)

    def _pdf(self, pages, *, message=None, filename="grant.pdf") -> AgentFile:
        file = make_file(
            self.user,
            message=message,
            filename=filename,
            text=PDF_TEXT,
            page_count=pages,
        )
        # The fake renderer never parses the original.
        file.etag = self.bucket.put(file.storage_key, b"%PDF-1.7", "application/pdf")
        file.save(update_fields=["etag"])
        return file

    def _image(self, *, message=None, filename="gel.png", text="") -> AgentFile:
        file = make_file(
            self.user,
            message=message,
            filename=filename,
            content_type="image/png",
            text=text,
        )
        file.etag = self.bucket.put(file.storage_key, image_bytes(), "image/png")
        file.save(update_fields=["etag"])
        return file


@override_settings(AWS_PRIVATE_STORAGE_BUCKET_NAME=BUCKET)
class ViewAttachmentPagesTests(BucketTestCase):
    def setUp(self):
        super().setUp()
        conversations = AgentConversationService()
        self.conversation = conversations.create(
            user=self.user, workflow="assistant_chat"
        )
        self.message = conversations.add_human_message(self.conversation, "See these")
        self.pdf = self._pdf(3, message=self.message)
        self.render = FakeRender()
        self.toolset = self._toolset(self.render)

    def _toolset(self, render, room=None):
        return AttachmentToolset(
            conversation=self.conversation,
            page_images=PageImageService(render=render),
            page_image_room=room,
        )

    def _view(self, attachment_id, pages, toolset=None):
        output, stop = (
            (toolset or self.toolset)
            .as_toolset()
            .call(
                VIEW_ATTACHMENT_PAGES, {"attachment_id": attachment_id, "pages": pages}
            )
        )
        self.assertFalse(stop)
        return output

    def test_the_pages_asked_for_are_shown_in_order(self):
        # Act
        output = self._view(self.pdf.id, [3, 1])

        # Assert
        self.assertEqual(
            output.content,
            {
                "attachment_id": self.pdf.id,
                "filename": "grant.pdf",
                "page_count": 3,
                "pages": [3, 1],
            },
        )
        self.assertEqual(output.images, (_page(self.pdf, 3), _page(self.pdf, 1)))
        for image in output.images:
            self.assertIn(image.ref, self.bucket.objects)

    def test_a_page_asked_for_twice_is_shown_once(self):
        # Act
        output = self._view(self.pdf.id, [2, 2, 1])

        # Assert
        self.assertEqual(output.content["pages"], [2, 1])
        self.assertEqual(len(output.images), 2)

    def test_a_file_that_is_not_a_pdf_has_no_pages_to_view(self):
        # Arrange
        cv = make_file(
            self.user,
            message=self.message,
            filename="cv.txt",
            content_type="text/plain",
            text="PhD, genomics.",
        )

        # Act
        output = self._view(cv.id, [1])

        # Assert
        self.assertIn("is not a PDF", output.content["error"])
        self.assertIn(READ_ATTACHMENT, output.content["error"])
        self.assertEqual(output.images, ())

    def test_an_uploaded_image_is_viewed_as_page_1(self):
        # Arrange
        gel = self._image(message=self.message)

        # Act
        shown = self._view(gel.id, [1])
        refused = self._view(gel.id, [2])

        # Assert
        self.assertEqual(shown.images, (_shown(gel),))
        self.assertEqual(
            refused.content["error"],
            f"attachment {gel.id} is an image; view it as page 1",
        )

    def test_a_page_the_file_does_not_have_is_refused(self):
        for pages in ([0], [4], [1, 4]):
            with self.subTest(pages=pages):
                # Act
                output = self._view(self.pdf.id, pages)

                # Assert
                self.assertEqual(
                    output.content["error"],
                    f"attachment {self.pdf.id} has 3 pages; pages must be "
                    "between 1 and 3",
                )
                self.assertEqual(output.images, ())
        self.assertEqual(self.render.pages, [])

    def test_one_call_shows_at_most_five_pages(self):
        # Arrange
        long = self._pdf(40, message=self.message, filename="plan.pdf")

        # Act
        five = self._view(long.id, [1, 2, 3, 4, 5])
        six = self._view(long.id, [6, 7, 8, 9, 10, 11])

        # Assert
        self.assertEqual(len(five.images), 5)
        self.assertIn("at most 5 pages per call", six.content["error"])
        self.assertEqual(six.images, ())
        self.assertEqual(sorted(self.render.pages), [1, 2, 3, 4, 5])

    def test_pages_must_be_a_list_of_numbers(self):
        for pages in (None, [], 2, "2", ["2"], [1.5], [True]):
            with self.subTest(pages=pages):
                # Act
                output = self._view(self.pdf.id, pages)

                # Assert
                self.assertEqual(
                    output.content["error"], "pages must be a list of page numbers"
                )
        self.assertEqual(self.render.pages, [])

    def test_a_page_that_cannot_be_rendered_is_named_and_the_rest_shown(self):
        # Arrange
        toolset = self._toolset(FakeRender(failing={2}))

        # Act
        some = self._view(self.pdf.id, [1, 2], toolset)
        none = self._view(self.pdf.id, [2], toolset)

        # Assert
        self.assertEqual(some.content["pages"], [1])
        self.assertEqual(some.content["pages_not_shown"], [2])
        self.assertEqual(some.images, (_page(self.pdf, 1),))
        self.assertEqual(
            none.content["error"],
            f"page 2 of attachment {self.pdf.id} could not be shown; work from "
            "the file's text",
        )
        self.assertEqual(none.images, ())

    def test_a_call_for_more_pages_than_the_chat_has_room_for_shows_what_fits(self):
        # Arrange: the chat has room for two more page images.
        toolset = self._toolset(self.render, room=2)

        # Act
        output = self._view(self.pdf.id, [3, 1, 2], toolset)

        # Assert: the page left out is named, and was not rendered.
        self.assertEqual(output.content["pages"], [3, 1])
        self.assertEqual(output.content["pages_without_room"], [2])
        self.assertEqual(
            output.content["note"],
            "This chat had room for only 2 more page images, so page 2 was not "
            "shown. Work from the file's text for it and say so rather than "
            "asking again.",
        )
        self.assertEqual(output.images, (_page(self.pdf, 3), _page(self.pdf, 1)))
        self.assertEqual(sorted(self.render.pages), [1, 3])

    def test_the_tool_refuses_once_the_chat_has_no_room_for_page_images(self):
        # Arrange: the first call takes the chat's last page image.
        toolset = self._toolset(self.render, room=1)
        self._view(self.pdf.id, [1], toolset)

        # Act
        output = self._view(self.pdf.id, [2], toolset)

        # Assert: said plainly, with nothing rendered.
        self.assertEqual(output.content, {"error": NO_ROOM_ERROR})
        self.assertEqual(output.images, ())
        self.assertEqual(self.render.pages, [1])

    def test_a_page_that_cannot_be_rendered_takes_no_room(self):
        # Arrange
        toolset = self._toolset(FakeRender(failing={1}), room=1)

        # Act
        failed = self._view(self.pdf.id, [1], toolset)
        shown = self._view(self.pdf.id, [2], toolset)

        # Assert
        self.assertIn("could not be shown", failed.content["error"])
        self.assertEqual(shown.images, (_page(self.pdf, 2),))

    def test_a_page_that_cannot_be_rendered_leaves_its_room_to_the_next(self):
        # Arrange: room for one more page image, and page 1 cannot be rendered.
        render = FakeRender(failing={1})
        toolset = self._toolset(render, room=1)

        # Act
        output = self._view(self.pdf.id, [1, 2, 3], toolset)

        # Assert: page 2 takes the room, and page 3 is not rendered.
        self.assertEqual(output.content["pages"], [2])
        self.assertEqual(output.content["pages_not_shown"], [1])
        self.assertEqual(output.content["pages_without_room"], [3])
        self.assertEqual(output.images, (_page(self.pdf, 2),))
        self.assertEqual(render.pages, [1, 2])

    def test_only_the_conversations_sent_files_can_be_viewed(self):
        # Arrange
        unsent = self._pdf(1)
        conversations = AgentConversationService()
        elsewhere = conversations.create(user=self.user, workflow="assistant_chat")
        other = self._pdf(
            1, message=conversations.add_human_message(elsewhere, "Another chat")
        )

        for file in (unsent, other):
            with self.subTest(file=file.id):
                # Act
                output = self._view(file.id, [1])

                # Assert
                self.assertIn(
                    "is not attached to this conversation", output.content["error"]
                )
        self.assertEqual(self.render.pages, [])

    def test_the_page_tool_is_offered_only_with_page_images(self):
        # Act
        without = AttachmentToolset(conversation=self.conversation).as_toolset()

        # Assert
        self.assertEqual(without.names, [READ_ATTACHMENT, SEARCH_ATTACHMENT])
        self.assertEqual(
            self.toolset.as_toolset().names,
            [READ_ATTACHMENT, SEARCH_ATTACHMENT, VIEW_ATTACHMENT_PAGES],
        )

    def test_the_model_is_told_what_an_unshown_image_means(self):
        # Arrange: the text an adapter puts where an image is not sent.
        tool = self.toolset.as_toolset().get(VIEW_ATTACHMENT_PAGES)
        prompts = [
            load_template("notebook_chat_system.txt"),
            load_template("assistant_chat_system.txt"),
        ]

        # Act / Assert
        for text in (tool.description, *prompts):
            flat = " ".join(text.split())
            self.assertIn(PLACEHOLDER, flat)
            self.assertIn("no room left for images", flat)
            self.assertIn("say so rather than asking for", flat)

    def test_activity_names_the_file_whose_pages_were_viewed(self):
        # Arrange
        at = datetime(2026, 10, 5, tzinfo=UTC)
        event = ToolCallEvent(
            tool=VIEW_ATTACHMENT_PAGES,
            input={"attachment_id": self.pdf.id, "pages": [3]},
            started_at=at,
            finished_at=at,
            result={"filename": "grant.pdf", "pages": [3]},
        )

        # Act
        (viewed,) = public_activity(
            [event],
            execution_active=True,
            answer_published=False,
            published_answer=None,
        )

        # Assert
        self.assertEqual(viewed["label"], "Looked at pages of an attached file")
        self.assertEqual(viewed["detail"], "grant.pdf")


class ToolRecordingProvider(FakeProvider):
    def complete(self, **kwargs):
        self.tools = kwargs["rendered_tools"]
        return super().complete(**kwargs)


@override_settings(**SETTINGS)
class ChatTurnTestCase(BucketTestCase):
    """Runs a chat's turns on a scripted provider, planned by ``delivery``."""

    delivery = DELIVERY

    def setUp(self):
        super().setUp()
        self.note = create_note(self.user, organization=None)[0]
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document.id,
            user=self.user,
        )
        self.render = FakeRender()
        self.service = self._service()
        self.conversation = self.service.create_conversation(self.note, self.user)

    def _service(self, provider=None, render=None, delivery=None):
        return NotebookChatService(
            provider=provider,
            oa_client=Mock(),
            web_search_client=Mock(configured=False),
            file_service=AgentFileService(delivery_config=delivery or self.delivery),
            page_image_service=PageImageService(render=render or self.render),
        )

    def _pick_models(self):
        """Staff may pick a model; the default tier's own is text-only."""
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

    def _submit(self, text, **kwargs):
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return self.service.submit_message(
                self.note, self.conversation, text, **kwargs
            )

    def _submit_to_vision_model(self, text, **kwargs):
        self._pick_models()
        return self._submit(text, model_ref=VISION_MODEL, **kwargs)

    def _finish(
        self,
        execution,
        *turns,
        render=None,
        provider_class=FakeProvider,
        delivery=None,
    ):
        provider = provider_class(list(turns))
        result = self._service(provider, render, delivery).run_turn(execution.id)
        self.assertNotIn("error", result)
        return provider

    def _retry(self, execution):
        execution.refresh_from_db()
        retry = self.service.chat.executions.create_pending(
            self.conversation,
            provider=execution.provider,
            model=execution.model,
            configuration=execution.configuration,
            system_prompt=execution.system_prompt,
            trigger_message=execution.trigger_message,
            context_parent=execution.context_parent,
            retry_of=execution,
            publish_assistant_message=True,
        )
        retry.usage_reservation_expires_at = claim_deadline()
        retry.save(update_fields=["usage_reservation_expires_at"])
        return retry

    def _manifest(self, message):
        """How each listed file reaches the model, from the turn's prompt."""
        lines = message.content[-1].text.split("\n")
        return [line.rsplit("): ", 1)[1] for line in lines if line.startswith("- ")]


class NotebookChatPageImageTests(ChatTurnTestCase):
    def test_a_short_pdfs_pages_are_sent_with_the_message(self):
        # Arrange
        grant = self._pdf(2)
        letter = self._pdf(1, filename="letter.pdf")
        execution = self._submit_to_vision_model(
            "What does figure 2 show?", file_ids=[grant.id, letter.id]
        )

        # Act
        provider = self._finish(execution, text_turn("A screen."))

        # Assert: file order, then page order, then the prompt.
        message = provider.calls[0][-1]
        self.assertEqual(
            message.content[:-1],
            [_page(grant, 1), _page(grant, 2), _page(letter, 1)],
        )
        self.assertIsInstance(message.content[-1], TextBlock)
        self.assertEqual(
            self._manifest(message),
            [f"full text below; {SHOWN}", f"full text below; {SHOWN}"],
        )
        self.assertEqual(sorted(self.render.pages), [1, 1, 2])

    def test_an_uploaded_image_is_sent_with_the_message(self):
        # Arrange
        gel = self._image()
        table = self._image(filename="table.png", text="Budget: $50,000")
        execution = self._submit_to_vision_model(
            "What do these show?", file_ids=[gel.id, table.id]
        )

        # Act
        provider = self._finish(execution, text_turn("A gel and a budget."))

        # Assert: only the image OCR read anything in has text to give.
        message = provider.calls[0][-1]
        self.assertEqual(message.content[:-1], [_shown(gel), _shown(table)])
        self.assertEqual(
            self._manifest(message),
            [
                "the image is shown with this message",
                "full text below; the image is shown with this message",
            ],
        )
        prompt = message.content[-1].text
        self.assertIn('"gel.png" (PNG image, no text was read in it)', prompt)
        self.assertIn(
            '"table.png" (PNG image, 15 characters read in it by OCR)', prompt
        )
        self.assertIn(f'id="{table.id}">\nBudget: $50,000\n', prompt)
        self.assertNotIn(f'id="{gel.id}"', prompt)

    def test_a_text_only_model_is_told_it_cannot_see_an_uploaded_image(self):
        # Arrange: the default tier's model takes no images.
        gel = self._image()
        execution = self._submit("What does this show?", file_ids=[gel.id])

        # Act
        provider = self._finish(execution, text_turn("I cannot view it."))

        # Assert
        message = provider.calls[0][-1]
        self.assertEqual([type(block) for block in message.content], [TextBlock])
        self.assertEqual(
            self._manifest(message), ["the image itself cannot be shown to you"]
        )
        self.mock_aws_client.get_object.assert_not_called()

    def test_a_second_turn_replays_the_first_turns_images_from_its_context(self):
        # Arrange
        grant = self._pdf(2)
        first = self._submit_to_vision_model("Describe it", file_ids=[grant.id])
        sent = self._finish(first, text_turn("Two pages.")).calls[0][-1]
        second = self._submit("And the budget?")
        self.mock_aws_client.reset_mock()

        # Act
        provider = self._finish(second, text_turn("Not given."))

        # Assert: the images come back as stored, with nothing rendered again.
        replayed = provider.calls[0][0]
        self.assertEqual(replayed.content, sent.content)
        self.assertEqual(replayed.content[:-1], [_page(grant, 1), _page(grant, 2)])
        self.assertEqual(provider.calls[0][-1].content, [TextBlock("And the budget?")])
        self.assertEqual(sorted(self.render.pages), [1, 2])
        self.mock_aws_client.head_object.assert_not_called()
        self.mock_aws_client.put_object.assert_not_called()

    def test_a_text_only_model_gets_no_images_and_no_page_tool(self):
        # Arrange: the default tier's model takes no images.
        grant = self._pdf(2)
        long = self._pdf(3, filename="plan.pdf")
        execution = self._submit("Describe them", file_ids=[grant.id, long.id])

        # Act
        provider = self._finish(
            execution, text_turn("Described."), provider_class=ToolRecordingProvider
        )

        # Assert: the block promises neither images nor the tool.
        self.assertEqual(execution.model, TEXT_ONLY_MODEL)
        message = provider.calls[0][-1]
        self.assertEqual([type(block) for block in message.content], [TextBlock])
        self.assertEqual(
            self._manifest(message), ["full text below", "full text below"]
        )
        self.assertNotIn("images", message.content[-1].text)
        self.assertNotIn(VIEW_ATTACHMENT_PAGES, provider.tools)
        self.assertIn(READ_ATTACHMENT, provider.tools)
        self.assertEqual(self.render.pages, [])
        self.mock_aws_client.head_object.assert_not_called()

    def test_a_page_that_fails_to_render_does_not_fail_the_turn(self):
        # Arrange
        grant = self._pdf(2)
        execution = self._submit_to_vision_model("Describe it", file_ids=[grant.id])

        # Act
        provider = self._finish(
            execution, text_turn("One page."), render=FakeRender(failing={2})
        )

        # Assert
        message = provider.calls[0][-1]
        self.assertEqual(message.content[:-1], [_page(grant, 1)])
        self.assertEqual(
            self._manifest(message),
            [f"full text below; {SHOWN}, except page 2, which could not be rendered"],
        )

    def test_a_storage_outage_does_not_fail_the_turn(self):
        # Arrange
        grant = self._pdf(2)
        gel = self._image()
        execution = self._submit_to_vision_model(
            "Describe them", file_ids=[grant.id, gel.id]
        )
        for call in ("head_object", "get_object", "put_object"):
            getattr(self.mock_aws_client, call).side_effect = RuntimeError("s3 down")

        # Act
        provider = self._finish(execution, text_turn("From the text."))

        # Assert: the file's text still arrives.
        message = provider.calls[0][-1]
        self.assertEqual([type(block) for block in message.content], [TextBlock])
        self.assertEqual(
            self._manifest(message),
            [
                "full text below; its pages could not be shown as images",
                "the image could not be shown",
            ],
        )
        self.assertIn(PDF_TEXT, message.content[-1].text)

    def test_a_retried_turn_sends_the_same_images_and_prompt(self):
        # Arrange: the first attempt stores the pages, then the provider fails.
        grant = self._pdf(2)
        execution = self._submit_to_vision_model("Describe it", file_ids=[grant.id])
        failing = FakeProvider([RuntimeError("provider down")])
        failed = self._service(failing).run_turn(execution.id)

        # Act
        provider = self._finish(self._retry(execution), text_turn("Two pages."))

        # Assert
        self.assertIn("error", failed)
        first, again = failing.calls[0][-1], provider.calls[0][-1]
        self.assertEqual(first.content[:-1], [_page(grant, 1), _page(grant, 2)])
        self.assertEqual(again.content, first.content)
        self.assertEqual(sorted(self.render.pages), [1, 2])

    def test_a_long_pdfs_pages_are_shown_when_the_model_asks(self):
        # Arrange
        long = self._pdf(3, filename="plan.pdf")
        execution = self._submit_to_vision_model(
            "What is on page 3?", file_ids=[long.id]
        )

        # Act
        provider = self._finish(
            execution,
            tool_turn(
                "t1", VIEW_ATTACHMENT_PAGES, {"attachment_id": long.id, "pages": [3]}
            ),
            text_turn("A timeline."),
        )

        # Assert: nothing is sent up front; the tool result carries the page.
        message = provider.calls[0][-1]
        self.assertEqual([type(block) for block in message.content], [TextBlock])
        self.assertEqual(self._manifest(message), [f"full text below; {ON_REQUEST}"])
        (result,) = provider.calls[1][-1].content
        self.assertEqual(result.content["pages"], [3])
        self.assertEqual(result.images, (_page(long, 3),))
        self.assertEqual(self.render.pages, [3])

    def test_any_pdf_in_the_chat_can_be_viewed_on_a_later_turn(self):
        # Arrange
        grant = self._pdf(2)
        first = self._submit_to_vision_model("Describe it", file_ids=[grant.id])
        self._finish(first, text_turn("Two pages."))
        second = self._submit("Look at page 2 again")

        # Act
        provider = self._finish(
            second,
            tool_turn(
                "t1", VIEW_ATTACHMENT_PAGES, {"attachment_id": grant.id, "pages": [2]}
            ),
            text_turn("A screen."),
        )

        # Assert
        (result,) = provider.calls[1][-1].content
        self.assertEqual(result.images, (_page(grant, 2),))

    def test_a_page_the_model_asked_for_is_replayed_on_later_turns(self):
        # Arrange
        long = self._pdf(3, filename="plan.pdf")
        first = self._submit_to_vision_model("What is on page 3?", file_ids=[long.id])
        self._finish(
            first,
            tool_turn(
                "t1", VIEW_ATTACHMENT_PAGES, {"attachment_id": long.id, "pages": [3]}
            ),
            text_turn("A timeline."),
        )
        second = self._submit("How long is it?")

        # Act
        provider = self._finish(second, text_turn("Two years."))

        # Assert: the tool result comes back from the stored context with its image.
        results = [
            block
            for message in provider.calls[0]
            for block in message.content
            if isinstance(block, ToolResultBlock)
        ]
        self.assertEqual([result.images for result in results], [(_page(long, 3),)])
        self.assertEqual(self.render.pages, [3])

    def test_the_page_tool_is_offered_on_every_turn_of_a_chat_that_takes_images(self):
        # Arrange: the chat has no file at all on its first turn.
        grant = self._pdf(2)
        long = self._pdf(3, filename="plan.pdf")
        turns = [{}, {"file_ids": [grant.id]}, {"file_ids": [long.id]}]

        # Act
        offered = []
        for options in turns:
            execution = self._submit_to_vision_model("Go on", **options)
            provider = self._finish(
                execution, text_turn("Done."), provider_class=ToolRecordingProvider
            )
            offered.append(provider.tools)

        # Assert: the tool list, part of the cached prefix, never changes.
        self.assertIn(VIEW_ATTACHMENT_PAGES, offered[0])
        self.assertEqual(offered[1], offered[0])
        self.assertEqual(offered[2], offered[0])

    def test_the_provider_is_given_a_loader_for_the_chats_images(self):
        # Arrange
        grant = self._pdf(1)
        execution = self._submit_to_vision_model("Describe it", file_ids=[grant.id])
        provider = FakeProvider([text_turn("One page.")])

        # Act
        with patch.object(
            chat_service, "resolve_provider", return_value=provider
        ) as resolve:
            self._service().run_turn(execution.id)

        # Assert: the loader reads the image the message refers to.
        loader = resolve.call_args.kwargs["image_loader"]
        (image,) = provider.calls[0][-1].content[:-1]
        self.assertIsInstance(loader, PrivateStorageImageLoader)
        self.assertEqual(loader(image.ref), self.bucket.objects[image.ref])

    def test_the_plan_and_the_adapter_judge_the_same_model(self):
        # Arrange: refs as an execution can record them, blank and bare included.
        keys = {
            BedrockProvider: "bedrock",
            ClaudePlatformProvider: "claude_platform",
            OpenRouterProvider: "openrouter",
        }
        cases = [
            ("claude_platform", ""),
            ("openrouter", ""),
            ("bedrock", ""),
            ("claude_platform", "claude-sonnet-5"),
            ("openrouter", "deepseek/deepseek-v4-flash-0731"),
            ("claude_platform", VISION_MODEL),
            ("claude_platform", TEXT_ONLY_MODEL),
            ("claude_platform", "openrouter:google/gemini-3.8-flash"),
            ("claude_platform", "bedrock:us.anthropic.claude-opus-5"),
            ("claude_platform", "bedrock:us.meta.llama4"),
        ]
        outcomes = set()
        for generator, model_ref in cases:
            with (
                self.subTest(generator=generator, model_ref=model_ref),
                override_settings(RESEARCH_AI_GENERATOR_PROVIDER=generator),
            ):
                # Act: the adapter the turn would run on, as the turn builds it.
                adapter = resolve_provider(model_ref or None)
                planned = chat_service._takes_images(model_ref)

                # Assert
                sends = model_capabilities(keys[type(adapter)], adapter.model_id).vision
                self.assertIs(planned, sends)
                outcomes.add(planned)
        self.assertEqual(outcomes, {True, False})


class ConversationPageImageBudgetTests(ChatTurnTestCase):
    # A chat takes four page images in all, two of them attached with messages.
    delivery = replace(
        DELIVERY,
        page_images_max_attached_per_conversation=2,
        page_images_max_per_conversation=4,
    )

    def _view(self, call_id, file, pages):
        return tool_turn(
            call_id, VIEW_ATTACHMENT_PAGES, {"attachment_id": file.id, "pages": pages}
        )

    def test_attached_pages_stop_at_their_share_of_the_chats_page_images(self):
        # Arrange: the first PDF's two pages are all that messages may attach.
        first = self._pdf(2, filename="first.pdf")
        sent = self._submit_to_vision_model("Describe it", file_ids=[first.id])
        self._finish(sent, text_turn("Two pages."))
        second = self._pdf(2, filename="second.pdf")
        execution = self._submit("And this one?", file_ids=[second.id])

        # Act
        provider = self._finish(
            execution, self._view("t1", second, [1, 2]), text_turn("Two more.")
        )

        # Assert: its pages are on request, and the chat's other two were kept.
        message = provider.calls[0][-1]
        self.assertEqual(self._manifest(message), [f"full text below; {ON_REQUEST}"])
        self.assertEqual([type(block) for block in message.content], [TextBlock])
        (result,) = provider.calls[1][-1].content
        self.assertEqual(result.images, (_page(second, 1), _page(second, 2)))

    def test_pages_viewed_with_the_tool_use_up_the_chats_page_images(self):
        # Arrange: four views over two calls, one page twice.
        long = self._pdf(3, filename="plan.pdf")
        first = self._submit_to_vision_model("Look through it", file_ids=[long.id])
        self._finish(
            first,
            self._view("t1", long, [1, 2, 3]),
            self._view("t2", long, [1]),
            text_turn("Seen."),
        )
        short = self._pdf(2)
        second = self._submit("And this one?", file_ids=[short.id])

        # Act
        provider = self._finish(
            second, self._view("t3", short, [1]), text_turn("From its text.")
        )

        # Assert: the new file's pages are not offered, and the tool refuses.
        message = provider.calls[0][-1]
        self.assertEqual(self._manifest(message), [f"full text below; {NO_ROOM}"])
        (result,) = provider.calls[1][-1].content
        self.assertEqual(result.content, {"error": NO_ROOM_ERROR})
        self.assertEqual(result.images, ())
        self.assertEqual(len(_images(provider.calls[1])), 4)

    def test_attached_and_viewed_pages_share_the_chats_page_images(self):
        # Arrange: two attached pages leave room for two of the three asked for.
        short = self._pdf(2)
        long = self._pdf(3, filename="plan.pdf")
        execution = self._submit_to_vision_model(
            "Compare them", file_ids=[short.id, long.id]
        )

        # Act
        provider = self._finish(
            execution, self._view("t1", long, [1, 2, 3]), text_turn("Compared.")
        )

        # Assert
        (result,) = provider.calls[1][-1].content
        self.assertEqual(result.content["pages"], [1, 2])
        self.assertEqual(result.content["pages_without_room"], [3])
        self.assertEqual(result.images, (_page(long, 1), _page(long, 2)))
        self.assertEqual(len(_images(provider.calls[1])), 4)

    def test_an_attached_page_that_fails_to_render_leaves_its_room_on_request(self):
        # Arrange: the short PDF's two pages are planned into the chat's only room.
        short = self._pdf(2)
        long = self._pdf(3, filename="plan.pdf")
        execution = self._submit_to_vision_model(
            "Compare them", file_ids=[short.id, long.id]
        )

        # Act: page 2 cannot be rendered.
        provider = self._finish(
            execution,
            self._view("t1", long, [1]),
            text_turn("Compared."),
            render=FakeRender(failing={2}),
            delivery=replace(DELIVERY, page_images_max_per_conversation=2),
        )

        # Assert: the long PDF's pages are offered, and the tool shows one.
        message = provider.calls[0][-1]
        self.assertEqual(
            self._manifest(message),
            [
                f"full text below; {SHOWN}, except page 2, which could not be rendered",
                f"full text below; {ON_REQUEST}",
            ],
        )
        (result,) = provider.calls[1][-1].content
        self.assertEqual(result.images, (_page(long, 1),))

    def test_a_retried_turn_plans_with_the_room_its_first_attempt_had(self):
        # Arrange: two pages were viewed; the message's two take the chat's last
        # room, and then the provider fails.
        long = self._pdf(3, filename="plan.pdf")
        sent = self._submit_to_vision_model("Look through it", file_ids=[long.id])
        self._finish(sent, self._view("t1", long, [1, 2]), text_turn("Seen."))
        short = self._pdf(2)
        execution = self._submit("And this one?", file_ids=[short.id])
        failing = FakeProvider([RuntimeError("provider down")])
        failed = self._service(failing).run_turn(execution.id)

        # Act
        provider = self._finish(self._retry(execution), text_turn("Two pages."))

        # Assert: the failed attempt's own pages do not count against the retry.
        self.assertIn("error", failed)
        attempt, again = failing.calls[0][-1], provider.calls[0][-1]
        self.assertEqual(attempt.content[:-1], [_page(short, 1), _page(short, 2)])
        self.assertEqual(again.content, attempt.content)

    def test_a_chat_already_over_the_budgets_keeps_what_it_was_sent(self):
        # Arrange: sent before the budgets, a file's text and pages are in the chat.
        earlier = self._pdf(2, filename="earlier.pdf")
        first = self._submit_to_vision_model("Describe it", file_ids=[earlier.id])
        sent = self._finish(first, text_turn("Two pages.")).calls[0][-1]
        budgets = replace(
            DELIVERY,
            inline_max_chars_per_conversation=len(PDF_TEXT) - 1,
            page_images_max_per_conversation=1,
        )
        later = self._pdf(1, filename="later.pdf")
        execution = self._submit("And this one?", file_ids=[later.id])

        # Act
        provider = self._finish(
            execution, text_turn("From its text."), delivery=budgets
        )

        # Assert: the earlier message is replayed whole; the new file adds nothing.
        self.assertEqual(provider.calls[0][0].content, sent.content)
        self.assertEqual(sent.content[:-1], [_page(earlier, 1), _page(earlier, 2)])
        self.assertIn(PDF_TEXT, sent.content[-1].text)
        message = provider.calls[0][-1]
        self.assertEqual(self._manifest(message), [f"{USE_TOOLS}; {NO_ROOM}"])
        self.assertEqual([type(block) for block in message.content], [TextBlock])
        self.assertNotIn(PDF_TEXT, message.content[-1].text)

    def test_a_text_only_model_is_told_nothing_about_room_for_images(self):
        # Arrange: the default tier's model, in a chat with no room for images.
        grant = self._pdf(2)
        execution = self._submit("Describe it", file_ids=[grant.id])

        # Act
        provider = self._finish(
            execution,
            text_turn("Described."),
            delivery=replace(DELIVERY, page_images_max_per_conversation=0),
        )

        # Assert
        self.assertEqual(execution.model, TEXT_ONLY_MODEL)
        message = provider.calls[0][-1]
        self.assertEqual(self._manifest(message), ["full text below"])
        self.assertNotIn("images", message.content[-1].text)

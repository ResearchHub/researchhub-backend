import io
import threading

import fitz
from django.contrib.auth import get_user_model
from django.test import override_settings
from PIL import Image

from research_ai.models import AgentConversation, AgentFile
from research_ai.services.agent.images import MANY_IMAGES, RequestImages
from research_ai.services.agent.providers import bedrock
from research_ai.services.agent.types import ImageBlock, Message
from research_ai.services.agent_files import AgentFileService
from research_ai.services.agent_files.extraction import UnreadableFileError
from research_ai.services.agent_files.image_loader import PrivateStorageImageLoader
from research_ai.services.agent_files.page_images import (
    MAX_PAGE,
    PageImageService,
    PageRenderConfig,
    page_image_keys,
)
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.tests.agent_files.helpers import (
    FakeBucket,
    FakeRender,
    make_file,
    pdf_bytes,
)
from utils.test_helpers import AWSMockTestCase

BUCKET = "researchhub-test-private-storage"
# 72 DPI keeps the real renders quick.
QUICK = PageRenderConfig(dpi=72)


class StallingRender(FakeRender):
    """Renders pages at once, except ``stalled`` ones, which wait for ``release``."""

    def __init__(self, stalled):
        super().__init__()
        self.stalled = set(stalled)
        self.release = threading.Event()

    def __call__(self, data, page, **options):
        if page in self.stalled:
            self.release.wait(timeout=30)
        return super().__call__(data, page, **options)


class PairedRender(FakeRender):
    """Renders a page only while another render is in flight."""

    def __init__(self):
        super().__init__()
        self.together = threading.Barrier(2, timeout=10)

    def __call__(self, data, page, **options):
        try:
            self.together.wait()
        except threading.BrokenBarrierError as exc:
            raise UnreadableFileError(f"page {page} was rendered alone") from exc
        return super().__call__(data, page, **options)


@override_settings(AWS_PRIVATE_STORAGE_BUCKET_NAME=BUCKET)
class PageImageServiceTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        conversations = AgentConversationService()
        self.conversation = conversations.create(
            user=self.user, workflow="assistant_chat"
        )
        self.message = conversations.add_human_message(self.conversation, "See this")
        self.bucket = FakeBucket(self.mock_aws_client)

    def _pdf(self, *pages, **fields) -> AgentFile:
        """A READY PDF sent in the chat, its original in the bucket."""
        fields.setdefault("message", self.message)
        data = fields.pop("data", None) or pdf_bytes(*pages)
        file = make_file(self.user, page_count=len(pages), **fields)
        file.etag = self.bucket.put(file.storage_key, data, "application/pdf")
        file.save(update_fields=["etag"])
        return file

    def _prefix(self, file) -> str:
        return file.storage_key.rsplit("/", 1)[0]

    def test_pages_are_rendered_stored_and_returned_in_the_order_asked(self):
        # Arrange
        file = self._pdf("Aims", "Approach", "Budget")

        # Act
        result = PageImageService(config=QUICK).images(file, [3, 1])

        # Assert
        prefix = self._prefix(file)
        self.assertEqual(
            result.images,
            (
                ImageBlock(f"{prefix}/pages/3.jpg", "image/jpeg", "grant.pdf, page 3"),
                ImageBlock(f"{prefix}/pages/1.jpg", "image/jpeg", "grant.pdf, page 1"),
            ),
        )
        self.assertEqual(result.failed, ())
        for image in result.images:
            self.assertEqual(self.bucket.content_types[image.ref], "image/jpeg")
            # The chat's image loader reads what was stored.
            data = PrivateStorageImageLoader()(image.ref)
            with Image.open(io.BytesIO(data)) as stored:
                self.assertEqual(stored.format, "JPEG")
                # An A4 page at 72 DPI.
                self.assertEqual(stored.size, (595, 842))

    def test_a_stored_page_is_reused_not_rendered_again(self):
        # Arrange
        file = self._pdf("Aims", "Approach")
        render = FakeRender()
        service = PageImageService(render=render)
        first = service.images(file, [1, 2])
        self.mock_aws_client.get_object.reset_mock()
        self.mock_aws_client.put_object.reset_mock()

        # Act
        again = service.images(file, [1, 2])

        # Assert
        self.assertEqual(again, first)
        self.assertEqual(sorted(render.pages), [1, 2])
        self.mock_aws_client.get_object.assert_not_called()
        self.mock_aws_client.put_object.assert_not_called()

    def test_the_original_is_read_once_per_call(self):
        # Arrange
        file = self._pdf("Aims", "Approach", "Budget")

        # Act
        PageImageService(render=FakeRender()).images(file, [1, 2, 3])

        # Assert
        self.mock_aws_client.get_object.assert_called_once_with(
            Bucket=BUCKET, Key=file.storage_key, IfMatch=file.etag
        )

    def test_a_replaced_original_is_not_rendered(self):
        # Arrange
        file = self._pdf("Aims", "Approach")
        service = PageImageService(render=FakeRender())
        service.images(file, [1])
        self.bucket.put(file.storage_key, pdf_bytes("Other"), "application/pdf")

        # Act
        result = service.images(file, [1, 2])

        # Assert: the page stored from the file's own original is still shown.
        self.assertEqual(
            [image.label for image in result.images], ["grant.pdf, page 1"]
        )
        self.assertEqual(result.failed, (2,))

    def test_a_missing_page_is_rendered_when_the_role_cannot_list_the_bucket(self):
        # Arrange: S3 answers 403, not 404, for a page not stored yet.
        self.bucket.listable = False
        file = self._pdf("Aims", "Approach")
        render = FakeRender()
        service = PageImageService(render=render)

        # Act
        first = service.images(file, [1, 2])
        again = service.images(file, [1, 2])

        # Assert
        self.assertEqual(len(first.images), 2)
        self.assertEqual(again, first)
        self.assertEqual(sorted(render.pages), [1, 2])

    def test_a_page_that_cannot_be_rendered_is_left_out_and_reported(self):
        # Arrange
        file = self._pdf("Aims", "Approach", "Budget")
        service = PageImageService(render=FakeRender(failing={2}))

        # Act
        result = service.images(file, [1, 2, 3])

        # Assert
        self.assertEqual(
            [image.label for image in result.images],
            ["grant.pdf, page 1", "grant.pdf, page 3"],
        )
        self.assertEqual(result.failed, (2,))
        self.assertNotIn(f"{self._prefix(file)}/pages/2.jpg", self.bucket.objects)

    def test_a_page_that_cannot_be_stored_is_reported(self):
        # Arrange
        file = self._pdf("Aims", "Approach")
        self.mock_aws_client.put_object.side_effect = RuntimeError("s3 unavailable")

        # Act
        result = PageImageService(render=FakeRender()).images(file, [1, 2])

        # Assert
        self.assertEqual(result.images, ())
        self.assertEqual(result.failed, (1, 2))

    def test_a_page_not_rendered_in_time_is_reported(self):
        # Arrange
        file = self._pdf("Aims", "Approach")
        render = StallingRender(stalled={2})
        self.addCleanup(render.release.set)
        service = PageImageService(
            config=PageRenderConfig(max_seconds=0.5), render=render
        )

        # Act
        result = service.images(file, [1, 2])

        # Assert
        self.assertEqual(
            [image.label for image in result.images], ["grant.pdf, page 1"]
        )
        self.assertEqual(result.failed, (2,))

    def test_pages_render_several_at_a_time(self):
        # Arrange
        file = self._pdf("Aims", "Approach")
        service = PageImageService(
            config=PageRenderConfig(concurrency=2), render=PairedRender()
        )

        # Act
        result = service.images(file, [1, 2])

        # Assert
        self.assertEqual(result.failed, ())

    def test_render_settings_come_from_django_settings(self):
        # Arrange
        file = self._pdf("Aims")

        # Act
        with override_settings(
            RESEARCH_AI_FILE_PAGE_RENDER_DPI=72,
            RESEARCH_AI_FILE_PAGE_RENDER_MAX_EDGE_PX=300,
        ):
            result = PageImageService().images(file, [1])

        # Assert
        with Image.open(io.BytesIO(self.bucket.objects[result.images[0].ref])) as image:
            self.assertEqual(max(image.size), 300)

    def test_a_large_page_at_the_default_settings_fits_a_crowded_request(self):
        # Arrange: a poster, and a request with enough images that a provider
        # takes none over 2000 px a side.
        poster = fitz.open()
        poster.new_page(width=36 * 72, height=48 * 72).insert_text((72, 72), "Aims")
        file = self._pdf("Aims", data=poster.tobytes())
        defaults = PageRenderConfig()
        (image,) = PageImageService().images(file, [1]).images
        crowded = [Message(role="user", content=[image] * (MANY_IMAGES + 1))]
        request = RequestImages(
            crowded,
            loader=PrivateStorageImageLoader(),
            vision=True,
            max_image_bytes=bedrock.MAX_IMAGE_BYTES,
            max_request_bytes=bedrock.MAX_REQUEST_IMAGE_BYTES,
        )

        # Act
        data = request.load(image)

        # Assert
        self.assertEqual(data, self.bucket.objects[image.ref])
        self.assertLessEqual(len(data), defaults.max_bytes)
        with Image.open(io.BytesIO(data)) as rendered:
            self.assertEqual(max(rendered.size), defaults.max_edge_px)

    def test_only_a_ready_pdf_has_page_images(self):
        # Arrange
        service = PageImageService(render=FakeRender())
        processing = self._pdf("Aims", status=AgentFile.Status.PROCESSING)
        word = make_file(
            self.user,
            message=self.message,
            filename="grant.docx",
            content_type="application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document",
        )

        # Act / Assert
        for file in (processing, word):
            with self.subTest(file=file.filename), self.assertRaises(ValueError):
                service.images(file, [1])
        self.mock_aws_client.put_object.assert_not_called()

    def test_a_page_the_file_does_not_have_is_refused(self):
        # Arrange
        file = self._pdf("Aims", "Approach")
        service = PageImageService(render=FakeRender())

        # Act / Assert
        for pages in ([0], [3], [1, 3], ["1"]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                service.images(file, pages)
        self.mock_aws_client.put_object.assert_not_called()

    def test_nothing_is_rendered_for_a_file_a_purge_would_delete(self):
        # Arrange
        service = PageImageService(render=FakeRender())
        unsent = self._pdf("Aims", message=None)
        ownerless = self._pdf("Aims")
        AgentFile.objects.filter(id=ownerless.id).update(user=None)
        removed_chat = AgentConversationService().create(
            user=self.user, workflow="assistant_chat"
        )
        in_removed_chat = self._pdf(
            "Aims",
            message=AgentConversationService().add_human_message(removed_chat, "Hi"),
        )
        AgentConversation.objects.filter(id=removed_chat.id).update(is_removed=True)

        for file in (unsent, ownerless, in_removed_chat):
            with self.subTest(file=file.id):
                # Act
                result = service.images(file, [1])

                # Assert
                self.assertEqual(result.images, ())
                self.assertEqual(result.failed, (1,))
        self.mock_aws_client.put_object.assert_not_called()

    def test_every_key_follows_from_the_page_count(self):
        # Arrange
        file = self._pdf("Aims", "Approach", "Budget")
        claimed = make_file(self.user, page_count=2**31 - 1)

        # Act
        result = PageImageService(render=FakeRender()).images(file, [1, 2, 3])

        # Assert
        self.assertEqual(page_image_keys(file), [image.ref for image in result.images])
        # A PDF can claim pages it does not have.
        self.assertEqual(len(page_image_keys(claimed)), MAX_PAGE)

    def test_purge_deletes_page_images_without_listing_the_bucket(self):
        # Arrange
        file = self._pdf("Aims", "Approach")
        PageImageService(render=FakeRender()).images(file, [1, 2])
        AgentConversation.objects.filter(id=self.conversation.id).update(
            is_removed=True
        )

        # Act
        purged = AgentFileService().purge()

        # Assert
        self.assertEqual(purged, 1)
        self.assertEqual(self.bucket.objects, {})
        self.assertFalse(AgentFile.objects.filter(id=file.id).exists())
        self.mock_aws_client.list_objects_v2.assert_not_called()
        self.mock_aws_client.get_paginator.assert_not_called()

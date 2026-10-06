from django.test import SimpleTestCase, override_settings

from research_ai.services.agent import images
from research_ai.services.agent.providers import bedrock, claude_platform, openrouter
from research_ai.services.agent_files.delivery import (
    ConversationUsage,
    Delivery,
    DeliveryConfig,
    Document,
    PageImages,
    TextDelivery,
    plan_delivery,
)
from research_ai.services.agent_files.page_images import PageRenderConfig

CONFIG = DeliveryConfig(
    inline_max_chars=1_000,
    inline_max_chars_per_message=1_500,
    page_images_max_pages=10,
    page_images_max_per_message=12,
    inline_max_chars_per_conversation=2_000,
    page_images_max_attached_per_conversation=12,
    page_images_max_per_conversation=15,
)


def _plan(*documents, vision=True, config=CONFIG, used=None):
    return plan_delivery(documents, vision=vision, config=config, used=used)


class PlanDeliveryTests(SimpleTestCase):
    def test_a_short_pdf_goes_inline_with_its_pages_attached(self):
        # Act
        (delivery,) = _plan(Document(text_chars=1_000, page_count=10))

        # Assert
        self.assertEqual(delivery, Delivery(TextDelivery.INLINE, PageImages.ATTACHED))

    def test_a_long_pdf_goes_behind_tools_with_pages_on_request(self):
        # Act
        (delivery,) = _plan(Document(text_chars=1_001, page_count=11))

        # Assert
        self.assertEqual(delivery, Delivery(TextDelivery.TOOLS, PageImages.ON_REQUEST))

    def test_text_length_and_page_count_are_judged_separately(self):
        # Act: a dense two-page PDF and a sparse forty-page one.
        dense, sparse = _plan(
            Document(text_chars=5_000, page_count=2),
            Document(text_chars=400, page_count=40),
        )

        # Assert
        self.assertEqual(dense, Delivery(TextDelivery.TOOLS, PageImages.ATTACHED))
        self.assertEqual(sparse, Delivery(TextDelivery.INLINE, PageImages.ON_REQUEST))

    def test_formats_without_pages_never_get_page_images(self):
        # Act
        word, empty = _plan(Document(text_chars=200), Document(200, page_count=0))

        # Assert
        self.assertEqual(word, Delivery(TextDelivery.INLINE, PageImages.NONE))
        self.assertEqual(empty, Delivery(TextDelivery.INLINE, PageImages.NONE))

    def test_a_model_without_vision_gets_text_only(self):
        # Act
        short, long = _plan(
            Document(text_chars=200, page_count=3),
            Document(text_chars=9_000, page_count=30),
            vision=False,
        )

        # Assert
        self.assertEqual(short, Delivery(TextDelivery.INLINE, PageImages.NONE))
        self.assertEqual(long, Delivery(TextDelivery.TOOLS, PageImages.NONE))

    def test_files_in_one_message_share_the_inline_budget(self):
        # Act: 900 + 500 fit the 1,500 budget; the next 500 does not.
        deliveries = _plan(
            Document(text_chars=900),
            Document(text_chars=500),
            Document(text_chars=500),
            Document(text_chars=100),
        )

        # Assert
        self.assertEqual(
            [delivery.text for delivery in deliveries],
            [
                TextDelivery.INLINE,
                TextDelivery.INLINE,
                TextDelivery.TOOLS,
                TextDelivery.INLINE,
            ],
        )

    def test_files_in_one_message_share_the_page_image_budget(self):
        # Act: 8 + 4 pages fill the budget of 12; the last 2 are on request.
        deliveries = _plan(
            Document(text_chars=100, page_count=8),
            Document(text_chars=100, page_count=5),
            Document(text_chars=100, page_count=4),
            Document(text_chars=100, page_count=2),
        )

        # Assert
        self.assertEqual(
            [delivery.page_images for delivery in deliveries],
            [
                PageImages.ATTACHED,
                PageImages.ON_REQUEST,
                PageImages.ATTACHED,
                PageImages.ON_REQUEST,
            ],
        )

    def test_inline_text_stops_at_what_the_conversation_has_left(self):
        # Arrange: 600 of the conversation's 2,000 characters are left.
        used = ConversationUsage(inline_chars=1_400)

        # Act
        deliveries = _plan(
            Document(text_chars=700), Document(text_chars=600), used=used
        )

        # Assert
        self.assertEqual(
            [delivery.text for delivery in deliveries],
            [TextDelivery.TOOLS, TextDelivery.INLINE],
        )

    def test_pages_past_the_attached_share_of_the_conversation_are_on_request(self):
        # Arrange: attached pages have 3 of their 12 left, the conversation 6 of 15.
        used = ConversationUsage(attached_page_images=9)

        # Act: 4 pages do not fit the share; 3 do, and use it up.
        deliveries = _plan(
            Document(text_chars=100, page_count=4),
            Document(text_chars=100, page_count=3),
            Document(text_chars=100, page_count=1),
            used=used,
        )

        # Assert: the conversation's other 3 are kept to be asked for.
        self.assertEqual(
            [delivery.page_images for delivery in deliveries],
            [PageImages.ON_REQUEST, PageImages.ATTACHED, PageImages.ON_REQUEST],
        )

    def test_no_page_can_be_asked_for_once_attached_pages_fill_the_conversation(self):
        # Arrange: pages the model asked for took 10 of the conversation's 15.
        used = ConversationUsage(requested_page_images=10)

        # Act: the second file's pages are attached and take the other five.
        deliveries = _plan(
            Document(text_chars=100, page_count=40),
            Document(text_chars=100, page_count=5),
            Document(text_chars=100, page_count=1),
            used=used,
        )

        # Assert
        self.assertEqual(
            [delivery.page_images for delivery in deliveries],
            [PageImages.NO_ROOM, PageImages.ATTACHED, PageImages.NO_ROOM],
        )

    def test_a_conversation_over_its_budgets_gets_tools_and_no_pages(self):
        # Arrange: as a chat can be whose files were sent before the budgets.
        used = ConversationUsage(inline_chars=9_000, attached_page_images=40)

        # Act
        (delivery,) = _plan(Document(text_chars=1, page_count=1), used=used)

        # Assert
        self.assertEqual(delivery, Delivery(TextDelivery.TOOLS, PageImages.NO_ROOM))

    def test_no_documents_plan_to_nothing(self):
        # Act / Assert
        self.assertEqual(_plan(), [])


class DeliveryConfigTests(SimpleTestCase):
    @override_settings(
        RESEARCH_AI_FILE_INLINE_MAX_CHARS=10,
        RESEARCH_AI_FILE_PAGE_IMAGES_MAX_PAGES=1,
    )
    def test_settings_override_the_thresholds(self):
        # Act
        (delivery,) = plan_delivery(
            [Document(text_chars=11, page_count=2)], vision=True
        )

        # Assert
        self.assertEqual(delivery, Delivery(TextDelivery.TOOLS, PageImages.ON_REQUEST))

    @override_settings(
        RESEARCH_AI_FILE_INLINE_MAX_CHARS_PER_CONVERSATION=10,
        RESEARCH_AI_FILE_PAGE_IMAGES_MAX_ATTACHED_PER_CONVERSATION=1,
        RESEARCH_AI_FILE_PAGE_IMAGES_MAX_PER_CONVERSATION=2,
    )
    def test_settings_override_the_conversation_budgets(self):
        # Arrange
        paper = Document(text_chars=11, page_count=2)
        full = ConversationUsage(requested_page_images=2)

        # Act: in a new conversation, then in one that carries two page images.
        (first,) = plan_delivery([paper], vision=True)
        (later,) = plan_delivery([paper], vision=True, used=full)

        # Assert
        self.assertEqual(first, Delivery(TextDelivery.TOOLS, PageImages.ON_REQUEST))
        self.assertEqual(later.page_images, PageImages.NO_ROOM)

    def test_the_defaults_keep_page_images_for_the_model_to_ask_for(self):
        # Arrange: attached pages have used their whole share of a conversation.
        share = DeliveryConfig().page_images_max_attached_per_conversation
        used = ConversationUsage(attached_page_images=share)

        # Act
        (delivery,) = plan_delivery(
            [Document(text_chars=1, page_count=1)], vision=True, used=used
        )

        # Assert
        self.assertEqual(delivery.page_images, PageImages.ON_REQUEST)

    def test_the_default_page_images_of_a_conversation_fit_any_providers_request(self):
        # Arrange: a page render is at most this large.
        pages = DeliveryConfig().page_images_max_per_conversation
        page_bytes = PageRenderConfig().max_bytes
        request_bytes = min(
            bedrock.MAX_REQUEST_IMAGE_BYTES,
            claude_platform.MAX_REQUEST_IMAGE_BYTES,
            openrouter.MAX_REQUEST_IMAGE_BYTES,
        )

        # Act / Assert: so none is ever sent as a placeholder.
        self.assertLessEqual(pages * page_bytes, request_bytes)
        self.assertLessEqual(pages, images.MAX_REQUEST_IMAGES)
        self.assertLessEqual(pages, bedrock.MAX_MESSAGE_IMAGES)

    def test_the_defaults_inline_a_short_paper_and_attach_its_pages(self):
        # Arrange
        defaults = DeliveryConfig()
        paper = Document(
            text_chars=defaults.inline_max_chars,
            page_count=defaults.page_images_max_pages,
        )

        # Act
        (delivery,) = plan_delivery([paper], vision=True)

        # Assert
        self.assertEqual(delivery, Delivery(TextDelivery.INLINE, PageImages.ATTACHED))

    def test_the_defaults_leave_a_longer_paper_to_tools_and_pages_on_request(self):
        # Arrange
        defaults = DeliveryConfig()
        paper = Document(
            text_chars=defaults.inline_max_chars + 1,
            page_count=defaults.page_images_max_pages + 1,
        )

        # Act
        (delivery,) = plan_delivery([paper], vision=True)

        # Assert
        self.assertEqual(delivery, Delivery(TextDelivery.TOOLS, PageImages.ON_REQUEST))

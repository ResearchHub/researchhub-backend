from django.test import SimpleTestCase, override_settings

from research_ai.services.agent_files.delivery import (
    Delivery,
    DeliveryConfig,
    Document,
    PageImages,
    TextDelivery,
    plan_delivery,
)

CONFIG = DeliveryConfig(
    inline_max_chars=1_000,
    inline_max_chars_per_message=1_500,
    page_images_max_pages=10,
    page_images_max_per_message=12,
)


def _plan(*documents, vision=True, config=CONFIG):
    return plan_delivery(documents, vision=vision, config=config)


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

    def test_the_defaults_inline_a_short_paper_and_attach_its_pages(self):
        # Act
        (delivery,) = plan_delivery(
            [Document(text_chars=45_000, page_count=12)], vision=True
        )

        # Assert
        self.assertEqual(delivery, Delivery(TextDelivery.INLINE, PageImages.ATTACHED))

from unittest.mock import Mock

from django.core.files.base import ContentFile
from django.test import override_settings

from purchase.services.partner_rfp_catalog import PartnerRfpTopic
from purchase.services.partner_rfp_import_service import PartnerRfpImportService
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import AWSMockTestCase


@override_settings(
    STORAGES={"default": {"BACKEND": "django.core.files.storage.InMemoryStorage"}}
)
class PartnerRfpBodyFileTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.owner = create_random_authenticated_user("partner_body_owner")
        self.service = PartnerRfpImportService(
            partner_organization="example-foundation", cover_service=Mock()
        )
        self.topic = PartnerRfpTopic(
            "Dog longevity",
            "Helping Dogs Live Longer, Healthier Lives",
            "Research into safe treatments that give pet dogs more healthy years.",
            ("dogs", "canine aging"),
        )

    def test_import_stores_body_as_text_file(self):
        # Act
        post, _ = self.service.import_topic(self.topic, owner=self.owner)

        # Assert
        self.assertTrue(post.discussion_src.name.endswith(".txt"))
        self.assertEqual(post.get_full_markdown(), post.renderable_text)

    def test_retry_keeps_body_stored_under_previous_name(self):
        # Arrange
        post, _ = self.service.import_topic(self.topic, owner=self.owner)
        post.discussion_src.save(
            f"partner-rfp-{post.pk}.html",
            ContentFile(post.renderable_text.encode("utf-8")),
            save=True,
        )
        previous_name = post.discussion_src.name

        # Act
        retried, created = self.service.import_topic(self.topic, owner=self.owner)

        # Assert
        self.assertFalse(created)
        self.assertEqual(retried.discussion_src.name, previous_name)
        self.assertTrue(previous_name.endswith(".html"))
        self.assertEqual(retried.get_full_markdown(), post.renderable_text)

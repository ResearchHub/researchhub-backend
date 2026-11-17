import csv
import json
from dataclasses import replace
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from purchase.models import Grant
from purchase.serializers.grant_create_serializer import GrantCreateSerializer
from purchase.services.partner_rfp_catalog import PartnerRfpTopic
from purchase.services.partner_rfp_import_service import PartnerRfpImportService
from research_ai.models import CoverImageGeneration
from researchhub_document.models import ResearchhubPost
from user.models import Action
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import AWSMockTestCase


class PartnerRfpImportTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.owner = create_random_authenticated_user("partner_import_owner")
        self.moderator = create_random_authenticated_user(
            "partner_import_mod", moderator=True
        )
        self.cover_service = Mock()
        self.service = PartnerRfpImportService(
            partner_organization="example-foundation", cover_service=self.cover_service
        )
        self.topic = PartnerRfpTopic(
            "Dog longevity",
            "Helping Dogs Live Longer, Healthier Lives",
            "Research into safe treatments that give pet dogs more healthy years.",
            ("dogs", "canine aging"),
        )
        self.client = APIClient()

    def test_retry_reuses_id_and_preserves_edits(self):
        # Arrange
        post, _ = self.service.import_topic(self.topic, owner=self.owner)
        post.title = "An edited title"
        post.slug = "edited-slug"
        post.save()

        # Act
        reused, created = self.service.import_topic(
            replace(self.topic, title="Changed CSV title"), owner=self.owner
        )

        # Assert
        self.assertFalse(created)
        self.assertEqual(reused.pk, post.pk)
        self.assertEqual(reused.title, "An edited title")
        self.assertFalse(reused.unified_document.is_public)
        self.assertTrue(reused.unified_document.document_filter.is_excluded_in_feed)
        grant = reused.unified_document.grants.get()
        self.assertEqual(grant.amount, Decimal(0))
        self.assertEqual(grant.currency, "USD")
        self.assertEqual(grant.status, Grant.OPEN)
        self.cover_service.generate_for_batch.assert_not_called()

    def test_public_import_is_directly_visible_but_excluded_from_all_feed_views(self):
        # Arrange
        post, _ = self.service.import_topic(
            self.topic, owner=self.owner, is_public=True
        )
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        # Even if an old/stray entry exists, reads must still exclude it.
        entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=post_ct,
            object_id=post.pk,
            unified_document=post.unified_document,
            user=self.owner,
            content={},
            metrics={},
        )
        urls = ["/api/grant_feed/", "/api/activity_feed/"]

        # Act / Assert
        for user in (None, self.owner, self.moderator):
            self.client.force_authenticate(user)
            for url in urls:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(
                    entry.pk, [row["id"] for row in response.data["results"]]
                )
                if url == "/api/grant_feed/":
                    self.assertNotIn(
                        post.pk,
                        [
                            row["content_object"]["id"]
                            for row in response.data["results"]
                        ],
                    )
            response = self.client.get(f"/api/researchhubpost/{post.pk}/")
            self.assertEqual(response.status_code, 200)
        self.assertFalse(post.actions.get().display)

    def test_open_grant_stays_out_of_rfp_feed(self):
        # Arrange
        post, _ = self.service.import_topic(
            self.topic, owner=self.owner, is_public=True, grant_amount=Decimal(500)
        )
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.get("/api/grant_feed/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.unified_document.grants.get().status, Grant.OPEN)
        self.assertFalse(response.data["results"])

    def test_task_does_not_publish_an_excluded_public_document(self):
        # Arrange
        post, _ = self.service.import_topic(
            self.topic, owner=self.owner, is_public=True
        )

        # Act
        result = create_feed_entry(
            post.pk,
            ContentType.objects.get_for_model(post).pk,
            "PUBLISH",
            user_id=self.owner.pk,
        )

        # Assert
        self.assertIsNone(result)
        self.assertFalse(
            FeedEntry.objects.filter(unified_document=post.unified_document).exists()
        )
        self.assertFalse(
            Action.objects.get(
                object_id=post.pk, content_type=ContentType.objects.get_for_model(post)
            ).display
        )

    def test_export_contains_only_supplied_rfps_and_marks_every_one_live(self):
        # Arrange
        other_topic = replace(self.topic, topic="Cat longevity")
        for topic in (self.topic, other_topic):
            self.service.import_topic(topic, owner=self.owner)

        # Act
        payload = self.service.export([self.topic, other_topic], owner=self.owner)

        # Assert
        self.assertEqual(payload["source"], "researchhub")
        self.assertEqual(set(payload), {"source", "rfps"})
        self.assertEqual(len(payload["rfps"]), 2)
        for rfp in payload["rfps"]:
            self.assertRegex(rfp["id"], r"^\d+$")
            self.assertTrue(rfp["live"])
        self.assertIsNone(payload["rfps"][0]["image"])

    def test_completed_cover_is_reused_without_another_paid_call(self):
        # Arrange
        post, _ = self.service.import_topic(self.topic, owner=self.owner)
        generation = CoverImageGeneration.objects.create(
            created_by=self.owner,
            document_type="GRANT",
            title=post.title,
            subtitle=self.topic.topic,
            status=CoverImageGeneration.Status.COMPLETED,
            image_key="uploads/cover.jpg",
        )
        self.cover_service.image_url.return_value = "https://cdn.example.com/cover.jpg"

        # Act
        self.service.ensure_cover(post, self.topic)
        self.service.ensure_cover(post, self.topic)

        # Assert
        post.refresh_from_db()
        self.assertEqual(post.image, generation.image_key)
        self.cover_service.generate_for_batch.assert_not_called()

    def test_new_cover_uses_the_batch_generation_entry_point(self):
        # Arrange
        post, _ = self.service.import_topic(self.topic, owner=self.owner)
        self.cover_service.generate_for_batch.return_value = Mock(
            status=CoverImageGeneration.Status.COMPLETED,
            image_key="uploads/batch-cover.jpg",
        )
        self.cover_service.image_url.return_value = "https://cdn.example.com/batch.jpg"

        # Act
        self.service.ensure_cover(post, self.topic)

        # Assert
        self.cover_service.generate_for_batch.assert_called_once_with(
            user=self.owner,
            document_type="GRANT",
            title=post.title,
            subtitle=self.topic.topic,
        )
        self.cover_service.start.assert_not_called()
        post.refresh_from_db()
        self.assertEqual(post.image, "uploads/batch-cover.jpg")

    def test_another_owner_cannot_reuse_the_import(self):
        # Arrange
        self.service.import_topic(self.topic, owner=self.owner)

        # Act / Assert
        with self.assertRaisesRegex(ValueError, "another owner"):
            self.service.import_topic(self.topic, owner=self.moderator)

    def test_regular_grant_api_serializer_still_rejects_zero(self):
        # Arrange
        post, _ = self.service.import_topic(self.topic, owner=self.owner)
        serializer = GrantCreateSerializer(
            data={
                "post_id": post.pk,
                "amount": "0.00",
                "description": self.topic.summary,
            }
        )

        # Act
        valid = serializer.is_valid()

        # Assert
        self.assertFalse(valid)
        self.assertIn("amount must be greater than 0", str(serializer.errors))

    def test_batch_rejects_negative_amount_and_rolls_back_the_post(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValidationError):
            self.service.import_topic(
                self.topic, owner=self.owner, grant_amount=Decimal("-0.01")
            )
        self.assertFalse(ResearchhubPost.objects.exists())
        self.assertFalse(Grant.objects.exists())

    def test_positive_batch_amount_can_still_be_supplied(self):
        # Arrange / Act
        post, _ = self.service.import_topic(
            self.topic, owner=self.owner, grant_amount=Decimal(50000)
        )

        # Assert
        grant = post.unified_document.grants.get()
        self.assertEqual(grant.amount, Decimal(50000))
        self.assertEqual(grant.status, Grant.OPEN)

    def test_partners_do_not_reuse_each_others_posts(self):
        # Arrange
        other_service = PartnerRfpImportService(
            partner_organization="other-foundation", cover_service=self.cover_service
        )
        first, _ = self.service.import_topic(self.topic, owner=self.owner)

        # Act
        second, created = other_service.import_topic(self.topic, owner=self.owner)

        # Assert
        self.assertTrue(created)
        self.assertNotEqual(first.pk, second.pk)
        self.assertTrue(
            first.external_source_id.startswith("partner:example-foundation:")
        )
        self.assertTrue(
            second.external_source_id.startswith("partner:other-foundation:")
        )

    def catalog_file(self, directory):
        path = Path(directory) / "topics.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=["Topic", "Title", "Summary", "Keywords"]
            )
            writer.writeheader()
            writer.writerow(
                {
                    "Topic": self.topic.topic,
                    "Title": self.topic.title,
                    "Summary": self.topic.summary,
                    "Keywords": ",".join(self.topic.keywords),
                }
            )
        return path

    def test_shell_plus_command_exports_real_ids_and_resumes(self):
        # Arrange
        with TemporaryDirectory() as directory:
            path = self.catalog_file(directory)
            output = Path(directory) / "partner-rfps.json"

            # Act
            for _ in range(2):
                call_command(
                    "import_partner_rfps",
                    str(path),
                    partner_organization="example-foundation",
                    apply=True,
                    owner_id=self.owner.pk,
                    owner_email=self.owner.email,
                    public=True,
                    output=str(output),
                    stdout=StringIO(),
                )

            # Assert
            payload = json.loads(output.read_text())
            self.assertEqual(set(payload), {"source", "rfps"})
            self.assertEqual(len(payload["rfps"]), 1)
            self.assertTrue(payload["rfps"][0]["live"])
            post = ResearchhubPost.objects.get(title=self.topic.title)
            self.assertEqual(payload["rfps"][0]["id"], str(post.pk))
            self.assertEqual(post.unified_document.grants.get().amount, Decimal(0))
            self.assertEqual(
                ResearchhubPost.objects.filter(
                    external_source_id__startswith="partner:example-foundation:"
                ).count(),
                1,
            )
            self.assertTrue(
                ResearchhubPost.objects.get(
                    title=self.topic.title
                ).unified_document.is_public
            )

    def test_wrong_owner_email_fails_before_importing(self):
        # Arrange
        with TemporaryDirectory() as directory:
            path = self.catalog_file(directory)

            # Act / Assert
            with self.assertRaisesRegex(CommandError, "does not match"):
                call_command(
                    "import_partner_rfps",
                    str(path),
                    partner_organization="example-foundation",
                    apply=True,
                    owner_id=self.owner.pk,
                    owner_email="somebody-else@example.com",
                    output=str(Path(directory) / "rfps.json"),
                    stdout=StringIO(),
                )
            self.assertFalse(ResearchhubPost.objects.exists())

    def test_dry_run_does_not_import_or_export(self):
        # Arrange
        with TemporaryDirectory() as directory:
            path = self.catalog_file(directory)
            output = Path(directory) / "rfps.json"

            # Act
            call_command(
                "import_partner_rfps",
                str(path),
                partner_organization="example-foundation",
                output=str(output),
                stdout=StringIO(),
            )

            # Assert
            self.assertFalse(ResearchhubPost.objects.exists())
            self.assertFalse(output.exists())

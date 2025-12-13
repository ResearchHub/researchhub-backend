from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.models import model_to_dict
from django.test import TestCase
from PIL import Image
from rest_framework.test import APIRequestFactory

from hub.tests.helpers import create_hub
from paper.models import Figure, PaperVersion
from paper.serializers import DynamicPaperSerializer, PaperSerializer
from paper.tests import helpers
from review.models.peer_review_model import PeerReview
from user.tests.helpers import create_random_default_user


class PaperSerializersTests(TestCase):

    def setUp(self):
        pass

    def test_authors_field_is_optional(self):
        hub_1 = create_hub(name="Hub 1")
        hub_2 = create_hub(name="Hub 2")
        paper = helpers.create_paper(title="Serialized Paper Title")
        paper.unified_document.hubs.add(hub_1)
        paper.unified_document.hubs.add(hub_2)
        paper_dict = model_to_dict(paper)
        serialized = PaperSerializer(data=paper_dict)
        self.assertTrue(serialized.is_valid())

    def test_hubs_field_is_optional(self):
        paper = helpers.create_paper(title="Hubs Required")
        paper_dict = model_to_dict(paper)
        serialized = PaperSerializer(data=paper_dict)
        self.assertTrue(serialized.is_valid())

    def test_paper_serializer_default_paper_version(self):
        paper = helpers.create_paper(title="Serialized Paper Title")
        serialized = PaperSerializer(paper)
        self.assertEqual(serialized.data["version"], 1)
        self.assertEqual(
            serialized.data["version_list"],
            [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "published_date": paper.paper_publish_date,
                    "is_latest": True,
                }
            ],
        )

    def test_paper_serializer_paper_versions(self):
        # Create first paper and version
        paper = helpers.create_paper(title="Serialized Paper Title")
        PaperVersion.objects.create(
            paper=paper,
            version=1,
            base_doi="10.1234/test",
            message="Test Message",
            original_paper=paper,  # Add original_paper reference
            publication_status=PaperVersion.PREPRINT,
        )

        serialized = PaperSerializer(paper)
        self.assertEqual(serialized.data["version"], 1)
        self.assertEqual(
            serialized.data["version_list"],
            [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "message": "Test Message",
                    "publication_status": PaperVersion.PREPRINT,
                    "published_date": paper.paper_publish_date,
                    "is_latest": True,
                    "is_version_of_record": False,  # Not VoR
                }
            ],
        )

        # Create second version
        paper2 = helpers.create_paper(title="Serialized Paper Title V2")
        PaperVersion.objects.create(
            paper=paper2,
            version=2,
            base_doi="10.1234/test",
            message="Test Message 2",
            original_paper=paper,  # Link to original paper
            publication_status=PaperVersion.PUBLISHED,
        )

        # Test serialization of both versions
        serialized2 = PaperSerializer(paper2)
        self.assertEqual(serialized2.data["version"], 2)
        self.assertEqual(
            serialized2.data["version_list"],
            [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "message": "Test Message",
                    "publication_status": PaperVersion.PREPRINT,
                    "published_date": paper.paper_publish_date,
                    "is_latest": False,
                    "is_version_of_record": False,
                },
                {
                    "version": 2,
                    "paper_id": paper2.id,
                    "message": "Test Message 2",
                    "publication_status": PaperVersion.PUBLISHED,
                    "published_date": paper2.paper_publish_date,
                    "is_latest": True,
                    "is_version_of_record": True,  # Published VoR
                },
            ],
        )

    def test_dynamic_paper_serializer_paper_versions(self):
        # Create first paper and version
        paper = helpers.create_paper(title="Serialized Paper Title")
        PaperVersion.objects.create(
            paper=paper,
            version=1,
            base_doi="10.1234/test",
            message="Test Message",
            original_paper=paper,  # Add original_paper reference
            publication_status=PaperVersion.PREPRINT,
        )

        serialized = DynamicPaperSerializer(paper)
        self.assertEqual(serialized.data["version"], 1)
        self.assertEqual(
            serialized.data["version_list"],
            [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "message": "Test Message",
                    "publication_status": PaperVersion.PREPRINT,
                    "published_date": paper.paper_publish_date,
                    "is_latest": True,
                    "is_version_of_record": False,  # Not VoR
                }
            ],
        )

        # Create second version
        paper2 = helpers.create_paper(title="Serialized Paper Title V2")
        PaperVersion.objects.create(
            paper=paper2,
            version=2,
            base_doi="10.1234/test",
            message="Test Message 2",
            original_paper=paper,  # Link to original paper
            publication_status=PaperVersion.PUBLISHED,
        )

        # Test serialization of both versions
        serialized2 = DynamicPaperSerializer(paper2)
        self.assertEqual(serialized2.data["version"], 2)
        self.assertEqual(
            serialized2.data["version_list"],
            [
                {
                    "version": 1,
                    "paper_id": paper.id,
                    "message": "Test Message",
                    "publication_status": PaperVersion.PREPRINT,
                    "published_date": paper.paper_publish_date,
                    "is_latest": False,
                    "is_version_of_record": False,
                },
                {
                    "version": 2,
                    "paper_id": paper2.id,
                    "message": "Test Message 2",
                    "publication_status": PaperVersion.PUBLISHED,
                    "published_date": paper2.paper_publish_date,
                    "is_latest": True,
                    "is_version_of_record": True,  # Published VoR
                },
            ],
        )

    def test_peer_reviews(self):
        # Arrange
        paper = helpers.create_paper(title="paper1")
        user1 = create_random_default_user("user1")
        user2 = create_random_default_user("user2")
        peer_review1 = PeerReview.objects.create(paper=paper, user=user1)
        peer_review2 = PeerReview.objects.create(paper=paper, user=user2)

        # Act
        actual = DynamicPaperSerializer(paper)

        # Assert
        self.assertTrue(len(actual.data["peer_reviews"]) == 2)
        peer_review_ids = {review["id"] for review in actual.data["peer_reviews"]}
        expected_ids = {peer_review1.id, peer_review2.id}
        self.assertEqual(peer_review_ids, expected_ids)

    def test_update_with_hubs(self):
        """
        Verify that updating a paper with hubs works correctly.
        """
        # Arrange
        user = create_random_default_user("user1")
        factory = APIRequestFactory()
        request = factory.patch("/")
        request.user = user
        hub1 = create_hub(name="hub1")
        hub2 = create_hub(name="hub2")
        hub3 = create_hub(name="hub3")
        paper = helpers.create_paper(title="paper1")
        paper.unified_document.hubs.add(hub1, hub2)  # Initially add hub1 and hub2

        # Act
        data = {"hubs": [hub2.id, hub3.id]}  # Remove hub1 and add hub3
        serializer = PaperSerializer(
            instance=paper, data=data, context={"request": request}, partial=True
        )

        # Assert: unified_document hubs should be updated to hub2 and hub3 only
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        updated_hubs = set(updated.unified_document.hubs.all())
        self.assertSetEqual(updated_hubs, {hub2, hub3})

    def _create_test_figure(self, paper, figure_type=Figure.FIGURE, is_primary=False):
        """Helper to create a test figure."""
        img = Image.new("RGB", (500, 500), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        image_file = SimpleUploadedFile(
            "test_figure.jpg", buffer.getvalue(), content_type="image/jpeg"
        )
        return Figure.objects.create(
            paper=paper,
            figure_type=figure_type,
            is_primary=is_primary,
            file=image_file,
        )

    def test_first_figure_prioritizes_primary(self):
        """Test that first_figure prioritizes is_primary=True figures."""
        paper = helpers.create_paper(title="Test Paper")

        # Create figures in different order
        _ = self._create_test_figure(paper, figure_type=Figure.FIGURE, is_primary=False)
        primary_figure = self._create_test_figure(
            paper, figure_type=Figure.FIGURE, is_primary=True
        )
        _ = self._create_test_figure(paper, figure_type=Figure.FIGURE, is_primary=False)

        serializer = PaperSerializer(paper)
        first_figure_data = serializer.data.get("first_figure")

        # Should return the primary figure, not the first one created
        self.assertIsNotNone(first_figure_data)
        self.assertEqual(first_figure_data["id"], primary_figure.id)
        self.assertTrue(first_figure_data["is_primary"])

    def test_first_figure_falls_back_to_preview(self):
        """Test that first_figure falls back to PREVIEW if no primary figure."""
        paper = helpers.create_paper(title="Test Paper")

        preview_figure = self._create_test_figure(
            paper, figure_type=Figure.PREVIEW, is_primary=False
        )
        _ = self._create_test_figure(paper, figure_type=Figure.FIGURE, is_primary=False)

        serializer = PaperSerializer(paper)
        first_figure_data = serializer.data.get("first_figure")

        # Should return preview figure
        self.assertIsNotNone(first_figure_data)
        self.assertEqual(first_figure_data["id"], preview_figure.id)
        self.assertEqual(first_figure_data["figure_type"], Figure.PREVIEW)

    def test_first_figure_falls_back_to_any_figure(self):
        """Test that first_figure falls back to any figure if no primary or preview."""
        paper = helpers.create_paper(title="Test Paper")

        figure = self._create_test_figure(
            paper, figure_type=Figure.FIGURE, is_primary=False
        )

        serializer = PaperSerializer(paper)
        first_figure_data = serializer.data.get("first_figure")

        # Should return the figure
        self.assertIsNotNone(first_figure_data)
        self.assertEqual(first_figure_data["id"], figure.id)

    def test_first_figure_returns_none_when_no_figures(self):
        """Test that first_figure returns None when paper has no figures."""
        paper = helpers.create_paper(title="Test Paper")

        serializer = PaperSerializer(paper)
        first_figure_data = serializer.data.get("first_figure")

        self.assertIsNone(first_figure_data)

    def test_first_preview_prioritizes_primary(self):
        """Test that first_preview prioritizes is_primary=True figures."""
        paper = helpers.create_paper(title="Test Paper")

        _ = self._create_test_figure(
            paper, figure_type=Figure.PREVIEW, is_primary=False
        )
        primary_preview = self._create_test_figure(
            paper, figure_type=Figure.PREVIEW, is_primary=True
        )
        _ = self._create_test_figure(
            paper, figure_type=Figure.PREVIEW, is_primary=False
        )

        serializer = DynamicPaperSerializer(paper)
        first_preview_data = serializer.data.get("first_preview")

        # Should return the primary preview, not the first one created
        self.assertIsNotNone(first_preview_data)
        self.assertEqual(first_preview_data["id"], primary_preview.id)
        self.assertTrue(first_preview_data["is_primary"])

    def test_first_preview_falls_back_to_preview_figures(self):
        """Test that first_preview falls back to PREVIEW figures if no primary."""
        paper = helpers.create_paper(title="Test Paper")

        preview_figure = self._create_test_figure(
            paper, figure_type=Figure.PREVIEW, is_primary=False
        )
        _ = self._create_test_figure(paper, figure_type=Figure.FIGURE, is_primary=False)

        serializer = DynamicPaperSerializer(paper)
        first_preview_data = serializer.data.get("first_preview")

        # Should return preview figure
        self.assertIsNotNone(first_preview_data)
        self.assertEqual(first_preview_data["id"], preview_figure.id)
        self.assertEqual(first_preview_data["figure_type"], Figure.PREVIEW)

    def test_first_preview_falls_back_to_any_figure(self):
        """Test that first_preview falls back to any figure if no preview."""
        paper = helpers.create_paper(title="Test Paper")

        figure = self._create_test_figure(
            paper, figure_type=Figure.FIGURE, is_primary=False
        )

        serializer = DynamicPaperSerializer(paper)
        first_preview_data = serializer.data.get("first_preview")

        # Should return the figure
        self.assertIsNotNone(first_preview_data)
        self.assertEqual(first_preview_data["id"], figure.id)

    def test_first_preview_returns_none_when_no_figures(self):
        """Test that first_preview returns None when paper has no figures."""
        paper = helpers.create_paper(title="Test Paper")

        serializer = DynamicPaperSerializer(paper)
        first_preview_data = serializer.data.get("first_preview")

        self.assertIsNone(first_preview_data)

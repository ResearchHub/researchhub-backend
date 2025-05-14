from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from hub.models import Hub
from paper.models import Paper, PaperVersion
from paper.related_models.authorship_model import Authorship
from user.models import User
from user.related_models.author_model import Author


class PublishToResearchHubJournalTestCase(TestCase):
    def setUp(self):
        # Create users: regular user, moderator, and staff
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.moderator = User.objects.create_user(
            username="moduser", email="mod@example.com", password="modpass"
        )
        self.moderator.moderator = True
        self.moderator.save()

        self.staff = User.objects.create_user(
            username="staffuser", email="staff@example.com", password="staffpass"
        )
        self.staff.is_staff = True
        self.staff.save()

        # Create a hub
        self.hub = Hub.objects.create(name="Test Hub")

        # Create author - remove department from Author
        self.author = Author.objects.create(
            first_name="Test",
            last_name="Author",
        )

        # Create a paper to use as previous paper
        self.previous_paper = Paper.objects.create(
            title="Original Paper",
            paper_title="Original Scientific Paper",
            abstract="This is the original abstract",
            uploaded_by=self.user,
            paper_publish_date=timezone.now(),
        )

        # Add author to the paper with department in Authorship
        Authorship.objects.create(
            paper=self.previous_paper,
            author=self.author,
            author_position="first",
            is_corresponding=True,
            raw_author_name=f"{self.author.first_name} {self.author.last_name}",
            department="Chemistry",  # Department belongs in Authorship
        )

        # Add hub to the paper
        self.previous_paper.unified_document.hubs.add(self.hub)

        # Setup API client
        self.client = APIClient()

        # URL for the endpoint
        self.url = "/api/paper/publish_to_researchhub_journal/"

    @patch("utils.doi.DOI.register_doi_for_paper")
    def test_publish_to_journal_success(self, mock_register_doi):
        """Test successful publication to ResearchHub Journal"""
        # Mock the DOI registration response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_register_doi.return_value = mock_response

        # Login as moderator
        self.client.force_authenticate(user=self.moderator)

        # Make the request
        response = self.client.post(
            self.url, {"previous_paper_id": self.previous_paper.id}, format="json"
        )

        # Verify successful response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Get the new paper
        new_paper = Paper.objects.latest("id")

        # Verify data was copied from previous paper
        self.assertEqual(new_paper.title, self.previous_paper.title)
        self.assertEqual(new_paper.abstract, self.previous_paper.abstract)
        self.assertEqual(
            new_paper.uploaded_by, self.moderator
        )  # Should be the moderator who published it

        # Verify paper version was created
        paper_version = PaperVersion.objects.get(paper=new_paper)
        self.assertEqual(paper_version.journal, PaperVersion.RESEARCHHUB)
        self.assertEqual(paper_version.publication_status, PaperVersion.PUBLISHED)

        # Verify authorships were copied
        self.assertEqual(new_paper.authorships.count(), 1)
        authorship = new_paper.authorships.first()
        self.assertEqual(authorship.author, self.author)

        # Verify hubs were copied
        self.assertEqual(new_paper.unified_document.hubs.count(), 1)
        self.assertEqual(new_paper.unified_document.hubs.first(), self.hub)

    def test_publish_to_journal_requires_authentication(self):
        """Test that anonymous users cannot access the endpoint"""
        # Don't authenticate
        response = self.client.post(
            self.url, {"previous_paper_id": self.previous_paper.id}, format="json"
        )

        # Verify unauthorized response
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_publish_to_journal_requires_moderator(self):
        """Test that regular users cannot access the endpoint"""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.url, {"previous_paper_id": self.previous_paper.id}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_publish_to_journal_missing_previous_paper_id(self):
        """Test that providing no previous_paper_id returns a bad request"""
        # Login as moderator
        self.client.force_authenticate(user=self.moderator)

        response = self.client.post(self.url, {}, format="json")  # No previous_paper_id

        # Verify bad request response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("previous_paper_id is required", response.data["error"])

    def test_publish_to_journal_invalid_previous_paper_id(self):
        """Test that providing an invalid previous_paper_id returns a bad request"""
        # Login as moderator
        self.client.force_authenticate(user=self.moderator)

        response = self.client.post(
            self.url, {"previous_paper_id": 99999}, format="json"  # Invalid ID
        )

        # Verify bad request response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Previous paper not found", response.data["error"])

    @patch("utils.doi.DOI.register_doi_for_paper")
    def test_publish_to_journal_crossref_failure(self, mock_register_doi):
        """Test handling of Crossref API failures"""
        # Mock the DOI registration response with a failure
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "API Error"
        mock_register_doi.return_value = mock_response

        # Login as moderator
        self.client.force_authenticate(user=self.moderator)

        response = self.client.post(
            self.url, {"previous_paper_id": self.previous_paper.id}, format="json"
        )

        # Verify bad request response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Unable to register DOI", response.data["error"])

    @patch("utils.doi.DOI.register_doi_for_paper")
    def test_publish_to_journal_with_previous_versions(self, mock_register_doi):
        """Test publishing a paper that already has version information"""
        # Mock the DOI registration response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_register_doi.return_value = mock_response

        # Create a version for the previous paper
        PaperVersion.objects.create(
            paper=self.previous_paper,
            version=2,
            base_doi="10.1234/base.123",
            original_paper=self.previous_paper,
        )

        # Login as moderator
        self.client.force_authenticate(user=self.moderator)

        # Make the request
        response = self.client.post(
            self.url, {"previous_paper_id": self.previous_paper.id}, format="json"
        )

        # Verify successful response
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Get the new paper
        new_paper = Paper.objects.latest("id")

        # Verify version was incremented
        paper_version = PaperVersion.objects.get(paper=new_paper)
        self.assertEqual(paper_version.version, 3)
        self.assertEqual(paper_version.journal, PaperVersion.RESEARCHHUB)
        self.assertEqual(paper_version.publication_status, PaperVersion.PUBLISHED)

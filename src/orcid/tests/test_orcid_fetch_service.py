from unittest.mock import Mock

from allauth.socialaccount.models import SocialAccount, SocialToken
from django.test import TestCase

from orcid.services import OrcidFetchService
from orcid.tests.helpers import OrcidTestHelper
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author
from user.tests.helpers import create_random_default_user


class OrcidFetchServiceTests(TestCase):

    def setUp(self):
        self.mock_client = Mock()
        self.mock_openalex = Mock()
        self.mock_email_service = Mock()
        self.mock_process = Mock()
        self.service = OrcidFetchService(
            client=self.mock_client,
            openalex=self.mock_openalex,
            email_service=self.mock_email_service,
            process_works_fn=self.mock_process,
        )

    def test_extract_dois(self):
        # Arrange
        works = {
            "group": [
                {"work-summary": [{"external-ids": {"external-id": [
                    {"external-id-type": "doi", "external-id-value": "10.1/a"}
                ]}}]},
                {"work-summary": [{"external-ids": {"external-id": [
                    {"external-id-type": "pmid", "external-id-value": "123"},
                    {"external-id-type": "doi", "external-id-value": "10.1/b"}
                ]}}]},
            ]
        }

        # Act
        result = self.service._extract_dois(works)
        empty_result = self.service._extract_dois({"group": []})

        # Assert
        self.assertEqual(result, ["10.1/a", "10.1/b"])
        self.assertEqual(empty_result, [])

    def test_find_paper_by_doi(self):
        # Arrange
        paper = Paper.objects.create(title="T", doi="10.1/x")

        # Act
        found = self.service._find_paper_by_doi("https://doi.org/10.1/x")
        empty = self.service._find_paper_by_doi("")
        not_found = self.service._find_paper_by_doi("10.1/none")

        # Assert
        self.assertEqual(found, paper)
        self.assertIsNone(empty)
        self.assertIsNone(not_found)

    def test_sync_raises_for_invalid_author(self):
        # Arrange
        user = create_random_default_user("no_orcid")

        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.sync_papers(999999)
        with self.assertRaises(ValueError):
            self.service.sync_papers(user.author_profile.id)

    def test_sync_returns_zero_when_no_dois(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        self.mock_client.get_works.return_value = {"group": []}

        # Act
        result = self.service.sync_papers(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 0)

    def test_sync_skips_when_no_matching_paper(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/missing")
        self.mock_openalex.get_work_by_doi.return_value = OrcidTestHelper.make_openalex_work("10.1/missing")

        # Act
        result = self.service.sync_papers(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 0)

    def test_sync_merges_authorship_when_orcid_matches(self):
        """When user's ORCID matches an author on the paper, authorship is transferred."""
        # Arrange
        user = OrcidTestHelper.create_author()
        openalex_author = Author.objects.create(
            first_name="J", last_name="D",
            openalex_ids=[OrcidTestHelper.OPENALEX_AUTHOR_ID],
            created_source=Author.SOURCE_OPENALEX,
        )
        paper = Paper.objects.create(title="T", doi="10.1/x")
        Authorship.objects.create(paper=paper, author=openalex_author, author_position="middle")
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        self.mock_openalex.get_work_by_doi.return_value = OrcidTestHelper.make_openalex_work("10.1/x")

        # Act
        result = self.service.sync_papers(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 1)
        self.assertEqual(Authorship.objects.get(paper=paper).author, user.author_profile)
        openalex_author.refresh_from_db()
        self.assertEqual(openalex_author.merged_with_author, user.author_profile)

    def test_sync_does_not_link_when_orcid_not_in_paper(self):
        """Malicious user scenario: user adds paper to ORCID they didn't write."""
        # Arrange
        user = OrcidTestHelper.create_author()
        other_author = Author.objects.create(
            first_name="Real", last_name="Author",
            openalex_ids=["https://openalex.org/A9999999999"],
            created_source=Author.SOURCE_OPENALEX,
        )
        paper = Paper.objects.create(title="T", doi="10.1/x")
        Authorship.objects.create(paper=paper, author=other_author)
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        self.mock_openalex.get_work_by_doi.return_value = {
            "doi": "https://doi.org/10.1/x",
            "authorships": [
                {"author": {"id": "https://openalex.org/A1111111111", "orcid": None}, "author_position": "first"},
                {"author": {"id": "https://openalex.org/A9999999999", "orcid": "https://orcid.org/9999-9999-9999-9999"}, "author_position": "last"},
            ],
        }

        # Act
        result = self.service.sync_papers(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 0)
        self.assertFalse(Authorship.objects.filter(paper=paper, author=user.author_profile).exists())

    def test_sync_skips_existing_authorship(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        paper = Paper.objects.create(title="T", doi="10.1/x")
        Authorship.objects.create(paper=paper, author=user.author_profile)
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        self.mock_openalex.get_work_by_doi.return_value = OrcidTestHelper.make_openalex_work("10.1/x")

        # Act
        result = self.service.sync_papers(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 0)

    def test_sync_does_not_merge_author_with_user(self):
        """Authors with users attached should not be merged."""
        # Arrange
        other_orcid = "https://orcid.org/1111-1111-1111-1111"
        user = OrcidTestHelper.create_author("u1")
        other_user = OrcidTestHelper.create_author("u2", orcid_id=other_orcid)
        paper = Paper.objects.create(title="T", doi="10.1/x")
        Authorship.objects.create(paper=paper, author=other_user.author_profile)
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        self.mock_openalex.get_work_by_doi.return_value = OrcidTestHelper.make_openalex_work("10.1/x")

        # Act
        self.service.sync_papers(user.author_profile.id)

        # Assert
        other_user.author_profile.refresh_from_db()
        self.assertIsNone(other_user.author_profile.merged_with_author)

    def test_sync_requires_orcid_social_account(self):
        """User must have ORCID SocialAccount connected, not just orcid_id set."""
        # Arrange
        user = OrcidTestHelper.create_author(orcid_connected=False)
        openalex_author = Author.objects.create(
            first_name="J", last_name="D",
            openalex_ids=[OrcidTestHelper.OPENALEX_AUTHOR_ID],
            created_source=Author.SOURCE_OPENALEX,
        )
        paper = Paper.objects.create(title="T", doi="10.1/x")
        Authorship.objects.create(paper=paper, author=openalex_author)
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        self.mock_openalex.get_work_by_doi.return_value = OrcidTestHelper.make_openalex_work("10.1/x")

        # Act
        result = self.service.sync_papers(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 0)
        self.assertEqual(Authorship.objects.get(paper=paper).author, openalex_author)

    def test_sync_edu_emails_skips_when_no_user(self):
        # Act
        self.service._sync_edu_emails(None, "0000-0001")

        # Assert
        self.mock_email_service.fetch_verified_edu_emails.assert_not_called()

    def test_sync_edu_emails_updates_social_account(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        app = OrcidTestHelper.create_app()
        account = SocialAccount.objects.get(user=user)
        SocialToken.objects.create(account=account, token="access_token", app=app)
        self.mock_email_service.fetch_verified_edu_emails.return_value = ["user@stanford.edu"]

        # Act
        self.service._sync_edu_emails(user, OrcidTestHelper.ORCID_ID)

        # Assert
        account.refresh_from_db()
        self.assertEqual(account.extra_data["verified_edu_emails"], ["user@stanford.edu"])

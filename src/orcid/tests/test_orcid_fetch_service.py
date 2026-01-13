from unittest.mock import Mock

from allauth.socialaccount.models import SocialAccount, SocialToken
from django.core.cache import cache
from django.test import TestCase

from orcid.services import OrcidFetchService
from orcid.services.orcid_fetch_service import _normalize_orcid
from orcid.tests.helpers import OrcidTestHelper
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author
from user.tests.helpers import create_random_default_user


class NormalizeOrcidTests(TestCase):
    """Tests for the _normalize_orcid helper function."""

    def test_normalizes_all_formats_to_consistent_output(self):
        # Arrange
        cases = [
            ("https://orcid.org/0000-0001-2345-6789", "https://orcid.org/0000-0001-2345-6789", "0000-0001-2345-6789"),
            ("0000-0001-2345-6789", "https://orcid.org/0000-0001-2345-6789", "0000-0001-2345-6789"),
            (None, None, None),
            ("", None, None),
        ]

        # Act & Assert
        for input_val, expected_full, expected_bare in cases:
            full, bare = _normalize_orcid(input_val)
            self.assertEqual(full, expected_full, f"Failed for input: {input_val}")
            self.assertEqual(bare, expected_bare, f"Failed for input: {input_val}")


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
            self.service.sync_orcid(999999)
        with self.assertRaises(ValueError):
            self.service.sync_orcid(user.author_profile.id)

    def test_sync_returns_zero_when_no_dois(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        self.mock_client.get_works.return_value = {"group": []}

        # Act
        result = self.service.sync_orcid(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 0)

    def test_sync_skips_when_openalex_returns_nothing(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        self.mock_openalex.get_work_by_doi.return_value = None

        # Act
        result = self.service.sync_orcid(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 0)

    def test_sync_skips_when_no_matching_paper(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/missing")
        self.mock_openalex.get_work_by_doi.return_value = OrcidTestHelper.make_openalex_work("10.1/missing")

        # Act
        result = self.service.sync_orcid(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 0)

    def test_sync_merges_authorship_when_orcid_matches(self):
        """When user's ORCID matches an author on the paper, author is merged (not transferred)."""
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
        result = self.service.sync_orcid(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 1)
        # Authorship still points to original author (preserves display name)
        self.assertEqual(Authorship.objects.get(paper=paper).author, openalex_author)
        # But the author is marked as merged with user's author
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
        result = self.service.sync_orcid(user.author_profile.id)

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
        result = self.service.sync_orcid(user.author_profile.id)

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
        self.service.sync_orcid(user.author_profile.id)

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
        result = self.service.sync_orcid(user.author_profile.id)

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

    def test_sync_clears_author_caches(self):
        """Cache should be cleared for both user's author and paper's author after sync."""
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

        # Set cache values
        user_author_id = user.author_profile.id
        cache.set(f"author-{user_author_id}-publications", "cached_value")
        cache.set(f"author-{user_author_id}-summary-stats", "cached_value")
        cache.set(f"author-{openalex_author.id}-publications", "cached_value")
        cache.set(f"author-{openalex_author.id}-summary-stats", "cached_value")

        # Act
        self.service.sync_orcid(user.author_profile.id)

        # Assert - caches should be cleared
        self.assertIsNone(cache.get(f"author-{user_author_id}-publications"))
        self.assertIsNone(cache.get(f"author-{user_author_id}-summary-stats"))
        self.assertIsNone(cache.get(f"author-{openalex_author.id}-publications"))
        self.assertIsNone(cache.get(f"author-{openalex_author.id}-summary-stats"))

    def test_fix_user_author_authorships_creates_paper_author(self):
        """
        When user has OpenAlex IDs in their profile (from previous claims),
        authorships created directly with the user should be fixed to use
        a paper-specific author linked via merged_with_author.
        """
        # Arrange
        user = OrcidTestHelper.create_author()
        # Simulate user having previously claimed papers (has OpenAlex ID in profile)
        user.author_profile.openalex_ids = [OrcidTestHelper.OPENALEX_AUTHOR_ID]
        user.author_profile.save()

        paper = Paper.objects.create(title="T", doi="10.1/x")
        # Simulate authorship created directly with user's author (the bug)
        Authorship.objects.create(
            paper=paper,
            author=user.author_profile,
            author_position="first",
            is_corresponding=False,
        )

        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        openalex_work = OrcidTestHelper.make_openalex_work("10.1/x")
        # Set a display name that should be preserved
        openalex_work["authorships"][0]["author"]["display_name"] = "Paper Author Name"
        openalex_work["authorships"][0]["is_corresponding"] = False
        # Add authorship with empty ID to cover the continue branch (id: None filtered by sanitize)
        openalex_work["authorships"].append({"author": {"id": ""}, "author_position": "last"})
        self.mock_openalex.get_work_by_doi.return_value = openalex_work

        # Act
        self.service.sync_orcid(user.author_profile.id)

        # Assert
        # User's author should no longer have the OpenAlex ID
        user.author_profile.refresh_from_db()
        self.assertNotIn(OrcidTestHelper.OPENALEX_AUTHOR_ID, user.author_profile.openalex_ids)

        # A new paper-specific author should exist with the OpenAlex ID
        paper_author = Author.objects.get(openalex_ids__contains=[OrcidTestHelper.OPENALEX_AUTHOR_ID])
        self.assertNotEqual(paper_author.id, user.author_profile.id)
        self.assertEqual(paper_author.first_name, "Paper")
        self.assertEqual(paper_author.last_name, "Name")

        # Paper author should be linked to user via merged_with_author
        self.assertEqual(paper_author.merged_with_author, user.author_profile)

        # Authorship should now point to paper author, not user
        authorship = Authorship.objects.get(paper=paper)
        self.assertEqual(authorship.author, paper_author)
        self.assertEqual(authorship.raw_author_name, "Paper Author Name")

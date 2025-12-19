from unittest.mock import Mock

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
        self.mock_process = Mock()
        self.service = OrcidFetchService(
            client=self.mock_client, openalex=self.mock_openalex, process_works_fn=self.mock_process
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

    def test_get_author_position(self):
        # Arrange
        work = {"authorships": [
            {"author": {"orcid": "https://orcid.org/other"}, "author_position": "first"},
            {"author": {"orcid": OrcidTestHelper.ORCID_URL}, "author_position": "last"},
        ]}

        # Act
        found = self.service._get_author_position(work, OrcidTestHelper.ORCID_ID)
        not_found = self.service._get_author_position({"authorships": []}, OrcidTestHelper.ORCID_ID)

        # Assert
        self.assertEqual(found, "last")
        self.assertEqual(not_found, "middle")

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

    def test_sync_links_paper(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        paper = Paper.objects.create(title="T", doi="10.1/x")
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        self.mock_openalex.get_work_by_doi.return_value = OrcidTestHelper.make_openalex_work("10.1/x")

        # Act
        result = self.service.sync_papers(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 1)
        self.assertEqual(Authorship.objects.get(paper=paper).author, user.author_profile)

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

    def test_sync_updates_existing_authorship_with_same_orcid(self):
        # Arrange
        user = OrcidTestHelper.create_author()
        openalex_author = Author.objects.create(
            first_name="J", last_name="D", orcid_id=OrcidTestHelper.ORCID_URL, created_source=Author.SOURCE_OPENALEX
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

    def test_sync_does_not_merge_author_with_user(self):
        # Arrange
        user = OrcidTestHelper.create_author("u1")
        other_user = OrcidTestHelper.create_author("u2")
        paper = Paper.objects.create(title="T", doi="10.1/x")
        Authorship.objects.create(paper=paper, author=other_user.author_profile)
        self.mock_client.get_works.return_value = OrcidTestHelper.make_works_response("10.1/x")
        self.mock_openalex.get_work_by_doi.return_value = OrcidTestHelper.make_openalex_work("10.1/x")

        # Act
        result = self.service.sync_papers(user.author_profile.id)

        # Assert
        self.assertEqual(result["papers_processed"], 1)
        other_user.author_profile.refresh_from_db()
        self.assertIsNone(other_user.author_profile.merged_with_author)

from unittest import TestCase
from unittest.mock import patch, Mock

from paper.openalex_util import (
    create_authors,
    fetch_authors_for_works,
    build_oa_authors_by_work_id_dict,
)


class TestFetchAuthorsForWorksNullSafety(TestCase):
    """Test that fetch_authors_for_works handles null author data gracefully."""

    @patch("paper.openalex_util.OpenAlex")
    def test_author_is_none_in_authorship(self, mock_oa_cls):
        """When authorship has 'author': null, should skip without error."""
        mock_oa = mock_oa_cls.return_value
        mock_oa.get_authors.return_value = ([], None)

        works = [
            {
                "authorships": [
                    {"author": None},
                    {"author": {"id": "https://openalex.org/A123"}},
                ]
            }
        ]
        result = fetch_authors_for_works(works)
        self.assertIsInstance(result, list)

    @patch("paper.openalex_util.OpenAlex")
    def test_author_missing_id(self, mock_oa_cls):
        """When author dict has no 'id', should skip without error."""
        mock_oa = mock_oa_cls.return_value
        mock_oa.get_authors.return_value = ([], None)

        works = [
            {
                "authorships": [
                    {"author": {"display_name": "Jane Doe"}},
                ]
            }
        ]
        result = fetch_authors_for_works(works)
        self.assertIsInstance(result, list)

    @patch("paper.openalex_util.OpenAlex")
    def test_authorships_is_none(self, mock_oa_cls):
        """When authorships value is null, should not fail."""
        mock_oa = mock_oa_cls.return_value
        mock_oa.get_authors.return_value = ([], None)

        works = [{"authorships": None}]
        result = fetch_authors_for_works(works)
        self.assertIsInstance(result, list)


class TestBuildOaAuthorsByWorkIdNullSafety(TestCase):
    def test_null_author_in_authorship(self):
        works = [
            {
                "id": "W1",
                "authorships": [
                    {"author": None},
                ],
            }
        ]
        fetched = []
        result = build_oa_authors_by_work_id_dict(works, fetched)
        self.assertIn("W1", result)

    def test_authorships_is_none(self):
        works = [{"id": "W1", "authorships": None}]
        fetched = []
        result = build_oa_authors_by_work_id_dict(works, fetched)
        self.assertIn("W1", result)


class TestCreateAuthorsNullSafety(TestCase):
    @patch("user.related_models.author_model.Author")
    def test_empty_display_name_skipped(self, mock_author_cls):
        """Authors with empty display_name should be skipped."""
        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([]))
        mock_author_cls.objects.filter.return_value = mock_qs
        mock_author_cls.SOURCE_OPENALEX = "OPENALEX"
        mock_author_cls.objects.bulk_create = Mock()

        works = [
            {
                "authorships": [
                    {"author": {"id": "A1", "display_name": ""}},
                    {"author": {"id": "A2", "display_name": None}},
                ]
            }
        ]
        create_authors(works)
        if mock_author_cls.objects.bulk_create.called:
            created = list(mock_author_cls.objects.bulk_create.call_args[0][0])
            for author in created:
                self.assertNotEqual(author.first_name, "")

    @patch("user.related_models.author_model.Author")
    def test_null_author_in_authorship_skipped(self, mock_author_cls):
        """Authorships with null author should be safely handled."""
        mock_qs = Mock()
        mock_qs.__iter__ = Mock(return_value=iter([]))
        mock_author_cls.objects.filter.return_value = mock_qs
        mock_author_cls.SOURCE_OPENALEX = "OPENALEX"
        mock_author_cls.objects.bulk_create = Mock()

        works = [
            {
                "authorships": [
                    {"author": None},
                ]
            }
        ]
        create_authors(works)

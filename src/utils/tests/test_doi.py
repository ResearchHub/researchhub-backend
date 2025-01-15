import unittest
from unittest.mock import MagicMock, patch

from django.conf import settings

from ..doi import DOI


class TestDOI(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.doi = DOI(base_doi="10.55277/test123")
        self.test_url = "https://researchhub.com/test"
        self.test_title = "Test Research Paper"

        # Create mock author
        self.mock_author = MagicMock()
        self.mock_author.first_name = "John"
        self.mock_author.last_name = "Doe"
        self.mock_author.orcid_id = "0000-0002-1234-5678"

        # Create nested mock for institution
        mock_author_institution = MagicMock()
        mock_institution = MagicMock()
        mock_institution.display_name = "Test Institution"
        mock_institution.city = "Test City"
        mock_institution.region = "Test State"
        mock_author_institution.institution = mock_institution

        # Update author's institutions mock
        self.mock_author.institutions.first.return_value = mock_author_institution

    def test_init_with_no_params(self):
        doi = DOI()
        self.assertIsNotNone(doi.base_doi)
        self.assertIsNotNone(doi.doi)
        self.assertEqual(doi.doi, doi.base_doi)

    def test_init_with_base_doi(self):
        base = "10.1234/test"
        doi = DOI(base_doi=base)
        self.assertEqual(doi.base_doi, base)
        self.assertEqual(doi.doi, base)

    def test_init_with_version(self):
        version = 1
        doi = DOI(version=version)
        self.assertEqual(doi.doi, f"{doi.base_doi}.{version}")

    def test_init_with_version_and_base_doi(self):
        base = "10.1234/test"
        version = 1
        doi = DOI(base_doi=base, version=version)
        self.assertTrue(doi.doi.startswith(doi.base_doi))
        self.assertEqual(doi.doi, f"{base}.{version}")

    def test_generate_base_doi(self):
        doi = DOI()
        generated = doi._generate_base_doi()
        self.assertTrue(generated.startswith(settings.CROSSREF_DOI_PREFIX))
        self.assertTrue(
            len(generated)
            == settings.CROSSREF_DOI_SUFFIX_LENGTH + len(settings.CROSSREF_DOI_PREFIX)
        )

    def test_register_doi_basic(self):
        """Test basic DOI registration with minimal author info."""
        with patch("utils.doi.render_to_string") as mock_render, patch(
            "requests.post"
        ) as mock_post:
            # Add expected template name
            mock_render.return_value = "<test>xml</test>"

            self.doi.register_doi(
                authors=[self.mock_author],
                authorships=[],
                title=self.test_title,
                url=self.test_url,
            )

            # Verify render_to_string was called with correct template
            mock_render.assert_called_once()
            template_name, context = mock_render.call_args[0]
            self.assertEqual(template_name, "crossref.xml")
            self.assertEqual(context["title"], self.test_title)
            self.assertEqual(context["url"], self.test_url)
            self.assertEqual(context["doi"], self.doi.base_doi)
            self.assertEqual(len(context["contributors"]), 1)

            # Verify API call
            mock_post.assert_called_once_with(
                settings.CROSSREF_API_URL,
                files={
                    "operation": (None, "doMDUpload"),
                    "login_id": (None, settings.CROSSREF_LOGIN_ID),
                    "login_passwd": (None, settings.CROSSREF_LOGIN_PASSWORD),
                    "fname": ("crossref.xml", "<test>xml</test>"),
                },
            )

    def test_register_doi_multiple_authors(self):
        """Test DOI registration with multiple authors."""
        authors = []
        for i in range(3):
            author = MagicMock()
            author.first_name = f"Author{i}"
            author.last_name = f"Last{i}"
            author.orcid_id = f"0000-0000-0000-000{i}"
            author.institutions.first.return_value = None
            authors.append(author)

        with patch("requests.post") as mock_post, patch(
            "utils.doi.render_to_string"
        ) as mock_render:

            mock_post.return_value = MagicMock(status_code=200)
            self.doi.register_doi(authors, [], self.test_title, self.test_url)

            context = mock_render.call_args[0][1]
            self.assertEqual(len(context["contributors"]), 3)
            for i, contributor in enumerate(context["contributors"]):
                self.assertEqual(contributor["first_name"], f"Author{i}")
                self.assertEqual(contributor["last_name"], f"Last{i}")
                self.assertEqual(contributor["orcid"], f"0000-0000-0000-000{i}")

    def test_register_doi_with_institution_no_city(self):
        """Test DOI registration with institution but no city info."""
        # Create nested mock for institution without city
        mock_author_institution = MagicMock()
        mock_institution = MagicMock()
        mock_institution.display_name = "Test Institution"
        mock_institution.city = None
        mock_institution.region = None
        mock_author_institution.institution = mock_institution

        self.mock_author.institutions.first.return_value = mock_author_institution

        with patch("requests.post") as mock_post, patch(
            "utils.doi.render_to_string"
        ) as mock_render:
            mock_post.return_value = MagicMock(status_code=200)
            self.doi.register_doi(
                [self.mock_author], [], self.test_title, self.test_url
            )

            context = mock_render.call_args[0][1]
            contributor = context["contributors"][0]
            self.assertEqual(contributor["institution"]["name"], "Test Institution")
            self.assertIsNone(contributor["institution"]["place"])

    def test_register_doi_api_failure(self):
        """Test handling of API failure."""
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=500)

            response = self.doi.register_doi(
                [self.mock_author], [], self.test_title, self.test_url
            )

            self.assertEqual(response.status_code, 500)

    def test_register_doi_timestamp_and_dates(self):
        """Test timestamp and date handling in DOI registration."""
        with patch("requests.post") as mock_post, patch(
            "utils.doi.render_to_string"
        ) as mock_render, patch("time.time") as mock_time:

            mock_time.return_value = 1234567890
            mock_post.return_value = MagicMock(status_code=200)

            self.doi.register_doi(
                [self.mock_author], [], self.test_title, self.test_url
            )

            context = mock_render.call_args[0][1]
            self.assertEqual(context["timestamp"], 1234567890)
            self.assertIsInstance(context["publication_month"], int)
            self.assertIsInstance(context["publication_day"], int)
            self.assertIsInstance(context["publication_year"], int)

    def test_register_doi_for_post(self):
        """Test DOI registration for a post."""
        mock_post = MagicMock()
        mock_post.id = 123
        mock_post.slug = "test-post"

        with patch("requests.post") as mock_post_request, patch(
            "utils.doi.render_to_string"
        ) as mock_render:

            mock_post_request.return_value = MagicMock(status_code=200)

            response = self.doi.register_doi_for_post(
                authors=[self.mock_author], title=self.test_title, rh_post=mock_post
            )

            context = mock_render.call_args[0][1]
            self.assertEqual(
                context["url"], f"{settings.BASE_FRONTEND_URL}/post/123/test-post"
            )
            self.assertEqual(response.status_code, 200)

    def test_register_doi_for_paper(self):
        """Test DOI registration for a paper."""
        mock_paper = MagicMock()
        mock_paper.id = 456
        mock_paper.slug = "test-paper"

        with patch("requests.post") as mock_post_request, patch(
            "utils.doi.render_to_string"
        ) as mock_render:

            mock_post_request.return_value = MagicMock(status_code=200)

            response = self.doi.register_doi_for_paper(
                authors=[self.mock_author], title=self.test_title, rh_paper=mock_paper
            )

            context = mock_render.call_args[0][1]
            self.assertEqual(
                context["url"], f"{settings.BASE_FRONTEND_URL}/paper/456/test-paper"
            )
            self.assertEqual(response.status_code, 200)

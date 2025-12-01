import json
from unittest.mock import patch

from rest_framework.test import APITestCase

from hub.models import Hub
from paper.models import Paper
from paper.openalex_util import (
    OPENALEX_SOURCES_TO_JOURNAL_HUBS,
    clean_url,
    process_openalex_works,
)
from paper.paper_upload_tasks import (
    PREPRINT_SERVER_PATTERNS,
    _get_or_create_journal_hub,
    _get_preprint_hub,
)
from paper.related_models.citation_model import Citation
from user.related_models.author_model import Author
from utils.openalex import OpenAlex


class ProcessOpenAlexWorksTests(APITestCase):
    def setUp(self):
        with open("./paper/tests/openalex_works.json", "r") as file:
            response = json.load(file)
            self.works = response.get("results")

    @patch.object(OpenAlex, "get_authors")
    def test_create_papers_from_openalex_works(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]

            created_papers = Paper.objects.filter(doi__in=dois).order_by("doi")
            self.assertEqual(len(created_papers), 2)

            for paper in created_papers:
                created_citation = Citation.objects.filter(paper=paper)
                self.assertEqual(len(created_citation), 1)
                self.assertEqual(
                    created_citation[0].total_citation_count, paper.citations
                )
                self.assertEqual(created_citation[0].citation_change, paper.citations)

    @patch.object(OpenAlex, "get_authors")
    def test_creating_papers_should_create_related_concepts(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois).order_by("doi")

            paper_concepts = created_papers[0].unified_document.concepts.all()
            self.assertEqual(len(paper_concepts), 15)
            paper_concepts = created_papers[1].unified_document.concepts.all()
            self.assertEqual(len(paper_concepts), 20)

    @patch.object(OpenAlex, "get_authors")
    def test_creating_papers_should_create_related_topics(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois).order_by("doi")

            paper_topics = created_papers[0].unified_document.topics.all()
            self.assertEqual(len(paper_topics), 3)
            paper_topics = created_papers[1].unified_document.topics.all()
            self.assertEqual(len(paper_topics), 4)

    @patch.object(OpenAlex, "get_authors")
    def test_creating_papers_should_create_related_hubs(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois).order_by("doi")

            paper_hubs = created_papers[0].unified_document.hubs.all()
            self.assertEqual(len(paper_hubs), 2)
            paper_hubs = created_papers[1].unified_document.hubs.all()
            self.assertEqual(len(paper_hubs), 3)

    @patch.object(OpenAlex, "get_authors")
    def test_creating_papers_should_tag_with_reputation_hubs(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois).order_by("doi")

            paper_hubs = created_papers[0].unified_document.hubs.filter(
                is_used_for_rep=True
            )
            self.assertEqual(len(paper_hubs), 1)
            paper_hubs = created_papers[1].unified_document.hubs.filter(
                is_used_for_rep=True
            )
            self.assertEqual(len(paper_hubs), 2)

    @patch.object(OpenAlex, "get_authors")
    def test_updating_existing_papers_from_openalex_works(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            # First create paper
            work = self.works[0]
            work["title"] = "Old title"
            process_openalex_works([work])

            # Update paper
            work["title"] = "New title"
            work["cited_by_count"] = work["cited_by_count"] + 10
            process_openalex_works([work])

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            updated_paper = Paper.objects.filter(doi__in=dois).first()

            self.assertEqual(updated_paper.title, "New title")
            self.assertEqual(updated_paper.paper_title, "New title")

            created_citation = Citation.objects.filter(paper=updated_paper).order_by(
                "created_date"
            )
            self.assertEqual(len(created_citation), 2)
            self.assertEqual(
                created_citation[1].total_citation_count, updated_paper.citations
            )
            self.assertEqual(created_citation[1].citation_change, 10)

    @patch.object(OpenAlex, "get_authors")
    def test_create_authors_when_processing_work(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois).order_by("doi")

            authors = Author.objects.all()
            self.assertEqual(len(authors), 5)

            paper_authors = created_papers.first().authorships.all()
            self.assertEqual(len(paper_authors), 3)
            paper_authors = created_papers.last().authorships.all()
            self.assertEqual(len(paper_authors), 3)

    @patch.object(OpenAlex, "get_authors")
    def test_create_authors_when_processing_work_twice(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)
            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            created_papers = Paper.objects.filter(doi__in=dois).order_by("doi")

            authors = Author.objects.all()
            self.assertEqual(len(authors), 5)

            paper_authors = created_papers.first().authorships.all()
            self.assertEqual(len(paper_authors), 3)
            paper_authors = created_papers.last().authorships.all()
            self.assertEqual(len(paper_authors), 3)

    @patch.object(OpenAlex, "get_authors")
    def test_create_authorships_when_processing_work(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            paper = Paper.objects.filter(doi__in=dois).order_by("doi")

            authorships = paper[0].authorships.all()
            self.assertEqual(len(authorships), 3)
            authorships = paper[1].authorships.all()
            self.assertEqual(len(authorships), 3)

    @patch.object(OpenAlex, "get_authors")
    def test_create_authorships_when_processing_work_twice(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            # Arrange
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            # Act
            process_openalex_works(self.works)
            # Invoking the process twice should not create duplicate authorships
            process_openalex_works(self.works)

            # Assert
            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            paper = Paper.objects.filter(doi__in=dois).order_by("doi")

            authorships = paper[0].authorships.all()
            self.assertEqual(len(authorships), 3)
            authorships = paper[1].authorships.all()
            self.assertEqual(len(authorships), 3)

    @patch.object(OpenAlex, "get_authors")
    def test_create_authorships_when_processing_work_with_field_updates(
        self, mock_get_authors
    ):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            # Arrange
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            # Act
            process_openalex_works(self.works)

            # Changing some of the secondary attributes should not create duplicate
            # authorships in a subsequent call
            for work in self.works:
                for authorship in work["authorships"]:
                    authorship["is_corresponding"] = True
                    authorship["author_position"] = "pos1"
                    authorship["author"]["display_name"] = "name1"

            process_openalex_works(self.works)

            # Assert
            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            paper = Paper.objects.filter(doi__in=dois).order_by("doi").first()

            authorships = paper.authorships.all()

            self.assertEqual(len(authorships), 3)
            for authorship in authorships:
                self.assertTrue(authorship.is_corresponding)
                self.assertEqual(authorship.author_position, "pos1")
                self.assertEqual(authorship.raw_author_name, "name1")

    @patch.object(OpenAlex, "get_authors")
    def test_create_authorship_institutions_when_processing_work(
        self, mock_get_authors
    ):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)

            dois = [work.get("doi") for work in self.works]
            dois = [doi.replace("https://doi.org/", "") for doi in dois]
            paper = Paper.objects.filter(doi__in=dois).order_by("doi")

            authorships = paper[0].authorships.all().order_by("paper_id", "author_id")
            institutions = authorships[0].institutions.all().order_by("openalex_id")
            self.assertEqual(len(institutions), 1)
            institutions = authorships[1].institutions.all().order_by("openalex_id")
            self.assertEqual(len(institutions), 0)

            authorships = paper[1].authorships.all().order_by("paper_id", "author_id")
            institutions = authorships[0].institutions.all().order_by("openalex_id")
            self.assertEqual(len(institutions), 1)
            institutions = authorships[1].institutions.all().order_by("openalex_id")
            self.assertEqual(len(institutions), 1)
            institutions = authorships[2].institutions.all().order_by("openalex_id")
            self.assertEqual(len(institutions), 1)

    @patch.object(OpenAlex, "get_authors")
    def test_add_orcid_to_author_when_processing_work(self, mock_get_authors):
        # Note: In actuality orcid value could be null but the payload in this
        # test has an orcid value in order to test if orcid is set properly when exists in payload

        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            open_alex = OpenAlex()
            open_alex.get_authors()

            process_openalex_works(self.works)
            author = Author.objects.filter(orcid_id__isnull=False).first()
            self.assertIsNotNone(author.orcid_id)

    @patch.object(OpenAlex, "get_authors")
    def test_author_summary_stats_are_set(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            open_alex = OpenAlex()
            open_alex.get_authors()

            process_openalex_works(self.works)
            author = Author.objects.filter(
                openalex_ids__contains=[mock_data["results"][0]["id"]]
            ).first()

            self.assertGreater(author.h_index, 0)
            self.assertGreater(author.two_year_mean_citedness, 0)
            self.assertGreater(author.i10_index, 0)

    @patch.object(OpenAlex, "get_authors")
    def test_create_contribution_activity(self, mock_get_authors):
        with open("./paper/tests/openalex_authors.json", "r") as file:
            mock_data = json.load(file)
            mock_get_authors.return_value = (mock_data["results"], None)

            process_openalex_works(self.works)
            author = Author.objects.filter(
                openalex_ids__contains=[mock_data["results"][0]["id"]]
            ).first()

            self.assertGreater(len(author.contribution_summaries.all()), 0)

    def test_clean_url(self):
        url = "https://abc.com/def ghi"

        cleaned_url = clean_url(url)
        self.assertEqual(cleaned_url, "https://abc.com/def%20ghi")

    def test_get_or_create_journal_hub(self):
        # Arrange
        journal_name = "jorunalName1"

        # Act
        journal_hub = _get_or_create_journal_hub(journal_name)

        # Assert
        self.assertEqual(journal_hub.name, journal_name)

    def test_get_or_create_journal_hub_with_existing_hub(self):
        # Arrange
        journal_name = "jorunalName1"
        Hub.objects.create(name=journal_name, namespace=Hub.Namespace.JOURNAL)

        # Act
        journal_hub = _get_or_create_journal_hub(journal_name)

        # Assert
        self.assertEqual(journal_hub.name, journal_name)

    def test_get_or_create_journal_hub_witn_managed_journal_hub(self):
        # Arrange
        journal_name = next(iter(OPENALEX_SOURCES_TO_JOURNAL_HUBS))
        managed_journal_hub = Hub.objects.create(
            name=OPENALEX_SOURCES_TO_JOURNAL_HUBS.get(journal_name),
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act
        journal_hub = _get_or_create_journal_hub(journal_name)

        # Assert
        self.assertEqual(journal_hub.name, managed_journal_hub.name)

    def test_get_preprint_hub_biorxiv_from_doi(self):
        # Arrange
        biorxiv_hub = Hub.objects.create(
            name="Biorxiv",
            slug="biorxiv",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act - DOI containing "biorxiv"
        result = _get_preprint_hub("10.1101/2024.01.01.12345.biorxiv", None)

        # Assert
        self.assertEqual(result.id, biorxiv_hub.id)

    def test_get_preprint_hub_biorxiv_from_external_source(self):
        # Arrange
        biorxiv_hub = Hub.objects.create(
            name="Biorxiv",
            slug="biorxiv",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act - external_source containing "biorxiv"
        result = _get_preprint_hub(None, "bioRxiv (Cold Spring Harbor Laboratory)")

        # Assert
        self.assertEqual(result.id, biorxiv_hub.id)

    def test_get_preprint_hub_medrxiv(self):
        # Arrange
        medrxiv_hub = Hub.objects.create(
            name="Medrxiv",
            slug="medrxiv",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act
        result = _get_preprint_hub("10.1101/2024.01.01.12345", "medRxiv (Cold Spring Harbor Laboratory)")

        # Assert
        self.assertEqual(result.id, medrxiv_hub.id)

    def test_get_preprint_hub_arxiv(self):
        # Arrange
        arxiv_hub = Hub.objects.create(
            name="Arxiv",
            slug="arxiv",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act
        result = _get_preprint_hub("10.48550/arXiv.2401.12345", None)

        # Assert
        self.assertEqual(result.id, arxiv_hub.id)

    def test_get_preprint_hub_chemrxiv(self):
        # Arrange
        chemrxiv_hub = Hub.objects.create(
            name="Chemrxiv",
            slug="chemrxiv",
            namespace=Hub.Namespace.JOURNAL,
        )

        # Act
        result = _get_preprint_hub("10.26434/chemrxiv-2024-abc123", None)

        # Assert
        self.assertEqual(result.id, chemrxiv_hub.id)

    def test_get_preprint_hub_non_preprint(self):
        # Act - Non-preprint DOI should return None
        result = _get_preprint_hub("10.1000/xyz123", "Nature")

        # Assert
        self.assertIsNone(result)

    def test_get_preprint_hub_none_inputs(self):
        # Act - None inputs should return None
        result = _get_preprint_hub(None, None)

        # Assert
        self.assertIsNone(result)

    def test_get_preprint_hub_empty_strings(self):
        # Act - Empty string inputs should return None
        result = _get_preprint_hub("", "")

        # Assert
        self.assertIsNone(result)

    def test_preprint_server_patterns_constant(self):
        # Assert that the constant contains expected preprint servers
        self.assertIn("medrxiv", PREPRINT_SERVER_PATTERNS)
        self.assertIn("biorxiv", PREPRINT_SERVER_PATTERNS)
        self.assertIn("chemrxiv", PREPRINT_SERVER_PATTERNS)
        self.assertIn("arxiv", PREPRINT_SERVER_PATTERNS)

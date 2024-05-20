import json
from unittest.mock import patch

from rest_framework.test import APITestCase

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from user.related_models.author_model import Author
from utils.openalex import OpenAlex


class ProcessOpenAlexWorksTests(APITestCase):
    def setUp(self):
        with open("./paper/tests/openalex_works.json", "r") as file:
            response = json.load(file)
            self.works = response.get("results")

    def test_create_papers_from_openalex_works(self):
        process_openalex_works(self.works)

        dois = [work.get("doi") for work in self.works]
        dois = [doi.replace("https://doi.org/", "") for doi in dois]

        created_papers = Paper.objects.filter(doi__in=dois)
        self.assertEqual(len(created_papers), 2)

    def test_creating_papers_should_create_related_topics(self):
        process_openalex_works(self.works)

        dois = [work.get("doi") for work in self.works]
        dois = [doi.replace("https://doi.org/", "") for doi in dois]
        created_papers = Paper.objects.filter(doi__in=dois)

        # Sample the first paper to ensure it has concepts
        paper_concepts = created_papers.first().unified_document.concepts.all()
        self.assertGreater(len(paper_concepts), 0)

    def test_creating_papers_should_create_related_concepts(self):
        process_openalex_works(self.works)

        dois = [work.get("doi") for work in self.works]
        dois = [doi.replace("https://doi.org/", "") for doi in dois]
        created_papers = Paper.objects.filter(doi__in=dois)

        # Sample the first paper to ensure it has topics
        paper_topics = created_papers.first().unified_document.topics.all()
        self.assertGreater(len(paper_topics), 0)

    def test_creating_papers_should_create_related_hubs(self):
        process_openalex_works(self.works)

        dois = [work.get("doi") for work in self.works]
        dois = [doi.replace("https://doi.org/", "") for doi in dois]
        created_papers = Paper.objects.filter(doi__in=dois)

        # Sample the first paper to ensure it has topics
        paper_hubs = created_papers.first().unified_document.hubs.all()
        self.assertGreater(len(paper_hubs), 0)

    def test_updating_existing_papers_from_openalex_works(self):
        # First create paper
        work = self.works[0]
        work["title"] = "Old title"
        process_openalex_works([work])

        # Update paper
        work["title"] = "New title"
        process_openalex_works([work])

        dois = [work.get("doi") for work in self.works]
        dois = [doi.replace("https://doi.org/", "") for doi in dois]
        updated_paper = Paper.objects.filter(doi__in=dois).first()

        self.assertEqual(updated_paper.title, "New title")
        self.assertEqual(updated_paper.paper_title, "New title")

    def test_create_authors_when_processing_work(self):
        process_openalex_works(self.works)

        dois = [work.get("doi") for work in self.works]
        dois = [doi.replace("https://doi.org/", "") for doi in dois]
        created_papers = Paper.objects.filter(doi__in=dois)

        # Sample the first paper to ensure it has authors
        paper_authors = created_papers.first().authors.all()
        self.assertGreater(len(paper_authors), 0)

    def test_create_authorships_when_processing_work(self):
        process_openalex_works(self.works)

        dois = [work.get("doi") for work in self.works]
        dois = [doi.replace("https://doi.org/", "") for doi in dois]
        paper = Paper.objects.filter(doi__in=dois).first()

        authorships = paper.authorships.all()
        self.assertGreater(len(authorships), 0)

    def create_authorship_institutions_when_processing_work(self):
        process_openalex_works(self.works)

        dois = [work.get("doi") for work in self.works]
        dois = [doi.replace("https://doi.org/", "") for doi in dois]
        paper = Paper.objects.filter(doi__in=dois).first()

        authorship = paper.authorships.first()
        institutions = authorship.institutions.all()
        self.assertGreater(len(institutions), 0)

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

import json
import re

import responses
from rest_framework.test import APITestCase

from paper.exceptions import DuplicatePaperError
from paper.models import PaperSubmission
from paper.related_models.paper_model import Paper
from paper.tasks import (
    celery_create_paper,
    celery_crossref,
    celery_get_doi,
    celery_openalex,
)
from user.tests.helpers import create_random_default_user


class PaperSubmissionViewTests(APITestCase):
    def setUp(self):
        self.url = "https://pubmed.ncbi.nlm.nih.gov/33313563/"
        self.duplicate_url = "https://www.vitisgen2.org/research-in-plain-english/evaluating-and-mapping-grape-color-using-image-based-phenotyping/"
        self.true_doi = "10.34133/2020/8086309"
        self.paper_publish_date = "2020-04-24"
        self.concept_display_names = [
            "Computer science",
            "Mathematics",
            "Biology",
            "Artificial intelligence",
            "Botany",
            "Hue",
            "RGB color model",
            "Population",
            "Berry",
            "Lightness",
            "Image (mathematics)",
            "Quantitative trait locus",
            "Color space",
            "Color model",
        ]
        self.submitter = create_random_default_user("submitter")
        self.client.force_authenticate(self.submitter)

        # Creating a submission
        self.paper_submission = PaperSubmission.objects.create(
            url=self.url,
            uploaded_by=self.submitter,
        )
        self.duplicate_paper_submission = PaperSubmission.objects.create(
            url=self.url,
            uploaded_by=self.submitter,
        )

    @responses.activate
    def test_full_flow(self):
        self._install_mock_responses()
        self.client.force_authenticate(self.submitter)
        self._paper_submission_flow()
        self._duplicate_doi_flow()

    # tests celery_process_paper as used by PaperSubmissionViewSet
    def _paper_submission_flow(self):
        celery_data = (
            {"dois": [], "url": self.url, "uploaded_by_id": self.submitter.id},
            self.paper_submission.id,
        )

        celery_data_after_doi = celery_get_doi.apply((celery_data,)).result
        dois = celery_data_after_doi[0]["dois"]
        self.assertIn(self.true_doi, dois)

        celery_data_after_openalex = celery_openalex.apply((celery_data,)).result
        paper_publish_date = celery_data_after_openalex[0]["paper_publish_date"]
        self.assertEqual(self.paper_publish_date, paper_publish_date)
        concepts = celery_data_after_openalex[0]["concepts"]
        self.assertEqual(
            self.concept_display_names,
            [concept["display_name"] for concept in concepts],
        )

        celery_data_after_crossref = celery_crossref.apply((celery_data,)).result
        doi = celery_data_after_crossref[0]["doi"]
        self.assertEqual(self.true_doi, doi)

        paper_id = celery_create_paper.apply((celery_data,)).result
        self.assertEqual(isinstance(paper_id, int), True)

        self.assertEqual(
            set(self.concept_display_names),
            set(
                c.display_name
                for c in Paper.objects.get(pk=paper_id).unified_document.concepts.all()
            ),
        )

    def _duplicate_doi_flow(self):
        self.client.force_authenticate(self.submitter)
        celery_data = (
            {
                "dois": [],
                "url": self.duplicate_url,
                "uploaded_by_id": self.submitter.id,
            },
            self.duplicate_paper_submission.id,
        )

        celery_data_after_doi = celery_get_doi.apply((celery_data,)).result
        dois = celery_data_after_doi[0]["dois"]
        self.assertIn(self.true_doi, dois)

        celery_data_after_crossref = celery_crossref.apply((celery_data,)).result
        self.assertEqual(
            isinstance(celery_data_after_crossref, DuplicatePaperError), True
        )

    def _install_mock_responses(self):
        # https://api.openalex.org/works?filter=doi:10.34133/2020/8086309
        with open("./paper/tests/work_by_doi.json", "r") as response_body_file:
            works_json = json.load(response_body_file)
        works_response = responses.Response(
            method="GET",
            url=re.compile(r"^https://api.openalex.org/works"),
            json=works_json,
        )

        # https://api.openalex.org/concepts?filter=openalex_id
        # :https://openalex.org/C126537357
        # |https://openalex.org/C82990744
        # |https://openalex.org/C154945302
        # |https://openalex.org/C2908647359
        # |https://openalex.org/C2776034682
        # |https://openalex.org/C81941488
        # |https://openalex.org/C193601281
        # |https://openalex.org/C2961294
        # |https://openalex.org/C41008148
        # |https://openalex.org/C33923547
        with open(
            "./paper/tests/concepts_by_openalex_id.json", "r"
        ) as response_body_file:
            concepts_json = json.load(response_body_file)
        concepts_response = responses.Response(
            method="GET",
            url=re.compile(r"^https://api.openalex.org/concepts"),
            json=concepts_json,
        )

        responses.add(works_response)
        responses.add(concepts_response)
        responses.add_passthru(
            re.compile("^(?!https://api.openalex.org/(concepts|works))")
        )

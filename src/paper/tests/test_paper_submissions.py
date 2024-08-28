import json
import re

import responses
from rest_framework.test import APITestCase

from paper.exceptions import DuplicatePaperError
from paper.models import PaperSubmission
from paper.paper_upload_tasks import (
    celery_combine_doi,
    celery_combine_paper_data,
    celery_create_paper,
    celery_crossref,
    celery_get_doi,
    celery_openalex,
)
from paper.related_models.paper_model import Paper
from user.tests.helpers import create_random_default_user


class PaperSubmissionViewTests(APITestCase):
    def setUp(self):
        self.url = "https://pubmed.ncbi.nlm.nih.gov/33313563/"
        self.duplicate_url = "https://www.staging.researchhub.com/paper/131636/evaluating-and-mapping-grape-color-using-image-based-phenotyping/"
        self.true_doi = "10.34133/2020/8086309"
        self.paper_publish_date = "2020-01-01"
        self.concept_display_names = [
            "Computer science",
            "Biology",
            "Mathematics",
            "Sociology",
            "Artificial intelligence",
            "Population",
            "Botany",
            "Demography",
            "Image (mathematics)",
            "Quantitative trait locus",
            "RGB color model",
            "Berry",
            "Hue",
            "Color space",
            "Lightness",
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

    # tests celery_process_paper as used by PaperSubmissionViewSet
    def _paper_submission_flow(self):
        celery_data = (
            {"dois": [], "url": self.url, "uploaded_by_id": self.submitter.id},
            self.paper_submission.id,
        )

        celery_data_after_doi = celery_get_doi.apply((celery_data,)).result
        dois = celery_data_after_doi["dois"]
        self.assertIn(self.true_doi, dois)

        celery_data_with_doi = celery_combine_doi.apply(
            ([celery_data_after_doi],)
        ).result
        celery_data_after_openalex = celery_openalex.apply(
            (celery_data_with_doi,)
        ).result
        paper_publish_date = celery_data_after_openalex["data"]["paper_publish_date"]
        self.assertEqual(self.paper_publish_date, paper_publish_date)

        celery_data_after_crossref = celery_crossref.apply(
            (celery_data_with_doi,)
        ).result
        doi = celery_data_after_crossref["data"]["doi"]
        self.assertEqual(self.true_doi, doi)

        combined_celery_data = celery_combine_paper_data.apply(
            ([celery_data_after_openalex, celery_data_after_crossref],)
        ).result

        paper_id = celery_create_paper.apply((combined_celery_data,)).result
        self.assertEqual(isinstance(paper_id, int), True)

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
        celery_data_with_doi = celery_combine_doi.apply(
            ([celery_data_after_doi],)
        ).result
        self.assertEqual(isinstance(celery_data_with_doi, DuplicatePaperError), True)

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

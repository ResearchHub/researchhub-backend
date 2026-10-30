"""
Tests for OSF registration mapper.
"""

import copy

from django.test import TestCase

from paper.ingestion.mappers import OSFRegistrationMapper


class TestOSFRegistrationMapper(TestCase):
    """Test OSF registration mapper functionality."""

    def setUp(self):
        self.mapper = OSFRegistrationMapper()

        # Based on the Lifecycle Journal outcomes report https://osf.io/wzubg/
        self.sample_record = {
            "id": "wzubg",
            "doi": "10.17605/OSF.IO/WZUBG",
            "attributes": {
                "title": "Public Understanding of Inequality",
                "description": "This study aims to replicate the 1992 study.",
                "date_registered": "2026-08-31T21:21:16.905334",
                "withdrawn": False,
                "registration_responses": {
                    "340-5": "Cristóbal Moya, Carsten Schröder, Philipp Lersch",
                    "340-14": "Outcomes Report",
                    "340-18": "Do Laypeople Endorse the Axioms of Inequality Measurement?",  # noqa: E501
                    "340-20": "The transfer principle is foundational.",
                    "340-31": [],
                    "340-33": [
                        {
                            "file_id": "6a95f05866c17b15acfb8c0b",
                            "file_name": "outcomes_report_lifecycle.docx",
                            "file_urls": {
                                "download": "https://osf.io/download/6a95f05866c17b15acfb8c0b"
                            },
                        }
                    ],
                },
            },
            "provider": "Lifecycle Journal",
            "url": "https://osf.io/wzubg/",
            "contributors": [
                {
                    "full_name": "Philipp M. Lersch",
                    "given_name": "Philipp",
                    "family_name": "Lersch",
                },
            ],
            "response_labels": {
                "340-5": "Authorship Order:",
                "340-14": "Submission Type:",
                "340-18": "Short Title:",
                "340-20": "Abstract:",
                "340-31": "Cover Letter:",
                "340-33": "Manuscript File:",
            },
        }

    def test_validate(self):
        # Arrange
        withdrawn = copy.deepcopy(self.sample_record)
        withdrawn["attributes"]["withdrawn"] = True
        without_doi = copy.deepcopy(self.sample_record)
        del without_doi["doi"]

        # Act & Assert
        self.assertTrue(self.mapper.validate(self.sample_record))
        self.assertFalse(self.mapper.validate(withdrawn))
        self.assertFalse(self.mapper.validate(without_doi))

    def test_map_to_paper_prefers_submission_answers(self):
        # Act
        paper = self.mapper.map_to_paper(self.sample_record)

        # Assert
        self.assertEqual(paper.doi, "10.17605/osf.io/wzubg")
        self.assertEqual(
            paper.title, "Do Laypeople Endorse the Axioms of Inequality Measurement?"
        )
        self.assertEqual(paper.paper_title, paper.title)
        self.assertEqual(paper.abstract, "The transfer principle is foundational.")
        self.assertEqual(paper.paper_publish_date, "2026-08-31")
        self.assertEqual(paper.url, "https://osf.io/wzubg/")
        self.assertEqual(paper.external_source, "Lifecycle Journal")
        self.assertEqual(
            paper.external_metadata,
            {"external_id": "wzubg", "submission_type": "Outcomes Report"},
        )
        self.assertEqual(
            [author["full_name"] for author in paper.raw_authors],
            ["Cristóbal Moya", "Carsten Schröder", "Philipp Lersch"],
        )
        self.assertEqual(paper.raw_authors[0]["first_name"], "Cristóbal")
        self.assertEqual(paper.raw_authors[0]["last_name"], "Moya")

    def test_map_to_paper_falls_back_to_registration_attributes(self):
        # Arrange
        record = copy.deepcopy(self.sample_record)
        record["attributes"]["registration_responses"] = {}

        # Act
        paper = self.mapper.map_to_paper(record)

        # Assert
        self.assertEqual(paper.title, "Public Understanding of Inequality")
        self.assertEqual(paper.abstract, "This study aims to replicate the 1992 study.")
        self.assertEqual(
            paper.raw_authors,
            [
                {
                    "full_name": "Philipp M. Lersch",
                    "first_name": "Philipp",
                    "last_name": "Lersch",
                    "raw_name": "Philipp M. Lersch",
                }
            ],
        )

    def test_map_to_paper_pdf_url_only_for_pdf_manuscripts(self):
        # Arrange
        record = copy.deepcopy(self.sample_record)
        record["attributes"]["registration_responses"]["340-33"][0]["file_name"] = (
            "outcomes_report.pdf"
        )

        # Act
        docx_paper = self.mapper.map_to_paper(self.sample_record)
        pdf_paper = self.mapper.map_to_paper(record)

        # Assert
        self.assertIsNone(docx_paper.pdf_url)
        self.assertEqual(
            pdf_paper.pdf_url, "https://osf.io/download/6a95f05866c17b15acfb8c0b"
        )

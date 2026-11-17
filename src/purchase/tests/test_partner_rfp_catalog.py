import csv
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from purchase.services.partner_rfp_catalog import (
    PartnerRfpTopic,
    permanent_rfp_id,
    read_catalog,
    validate_https_url,
)


class PartnerRfpCatalogTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "topics.csv"
        self.row = {
            "Topic": "Dog longevity",
            "Title": "Helping Dogs Live Longer, Healthier Lives",
            "Summary": "Research into safe treatments for canine aging."
            + r"\n\nMore research.",
            "Keywords": "dogs, canine aging, dogs",
            "Image": "",
            "Research Flag": "Review claims",
        }

    def write_rows(self, rows):
        with self.path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.row))
            writer.writeheader()
            writer.writerows(rows)

    def test_reads_only_csv_topics_and_normalizes_their_content(self):
        # Arrange
        self.write_rows([self.row])

        # Act
        topics = read_catalog(self.path, partner_organization="example-foundation")

        # Assert
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0].topic, self.row["Topic"])
        self.assertIn("\n\n", topics[0].summary)
        self.assertEqual(topics[0].keywords, ("dogs", "canine aging"))
        self.assertEqual(topics[0].research_flag, "Review claims")

    def test_invalid_catalog_fails_with_source_row(self):
        # Arrange / Act / Assert
        for changes in (
            {"Title": "short"},
            {"Title": "A sufficiently long title\non two lines"},
            {"Summary": "x" * 2001},
            {"Summary": "Read https://example.com " + "research " * 10},
            {"Keywords": ",".join(f"word{i}" for i in range(51))},
            {"Keywords": "x" * 101},
            {"Image": "http://example.com/cover.jpg"},
        ):
            with self.subTest(changes=changes):
                self.write_rows([{**self.row, **changes}])
                with self.assertRaisesRegex(ValueError, "CSV row 2"):
                    read_catalog(self.path, partner_organization="example-foundation")

    def test_duplicate_topics_are_rejected_case_insensitively(self):
        # Arrange
        self.write_rows([self.row, {**self.row, "Topic": "DOG LONGEVITY"}])

        # Act / Assert
        with self.assertRaisesRegex(ValueError, "unique"):
            read_catalog(self.path, partner_organization="example-foundation")

    def test_import_identity_survives_title_changes(self):
        # Arrange
        topic = PartnerRfpTopic("Dogs", "First title", "Summary", ())

        # Act
        renamed = replace(topic, title="A completely different title")

        # Assert
        self.assertEqual(
            topic.source_id("example-foundation"),
            renamed.source_id("example-foundation"),
        )
        self.assertEqual(permanent_rfp_id(12345), "12345")

    def test_expiring_image_urls_are_rejected(self):
        # Arrange / Act / Assert
        with self.assertRaisesRegex(ValueError, "permanent public HTTPS"):
            validate_https_url("https://example.com/a.jpg?Expires=123&Signature=abc")

    def test_same_topic_has_separate_partner_identities(self):
        # Arrange
        topic = PartnerRfpTopic("Dogs", "First title", "Summary", ())

        # Act / Assert
        self.assertNotEqual(
            topic.source_id("example-foundation"), topic.source_id("other-foundation")
        )
        self.assertLessEqual(len(topic.source_id("x" * 48)), 128)

    def test_invalid_partner_is_rejected(self):
        # Arrange
        self.write_rows([self.row])

        # Act / Assert
        for partner in ("", "Has Spaces", "bad:namespace", "x" * 49):
            with (
                self.subTest(partner=partner),
                self.assertRaisesRegex(ValueError, "Partner organization"),
            ):
                read_catalog(self.path, partner_organization=partner)

    def test_catalog_accepts_the_full_2000_topic_limit(self):
        # Arrange
        self.write_rows([{**self.row, "Topic": f"Topic {i}"} for i in range(2000)])

        # Act
        topics = read_catalog(self.path, partner_organization="example-foundation")

        # Assert
        self.assertEqual(len(topics), 2000)
        self.assertEqual(topics[-1].topic, "Topic 1999")

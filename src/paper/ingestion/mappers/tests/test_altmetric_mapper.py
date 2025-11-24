from datetime import datetime, timezone

from django.test import TestCase

from paper.ingestion.mappers import AltmetricMapper


class AltmetricMapperTests(TestCase):
    def setUp(self):
        self.sample_response = {
            "title": "Climate change will hit genetic diversity",
            "doi": "10.1038/news.2011.490",
            "isbns": [],
            "altmetric_jid": "4f6fa50a3cf058f610003160",
            "issns": ["0028-0836", "1476-4687"],
            "journal": "Nature",
            "cohorts": {"pub": 117, "doc": 1, "sci": 10, "com": 5},
            "context": {
                "all": {
                    "count": 28840878,
                    "mean": 10.743154505767821,
                    "rank": 333214,
                    "pct": 98,
                    "higher_than": 28507882,
                },
                "journal": {
                    "count": 105825,
                    "mean": 99.47329723600286,
                    "rank": 17103,
                    "pct": 83,
                    "higher_than": 88721,
                },
                "similar_age_3m": {
                    "count": 144282,
                    "mean": 8.66527493381019,
                    "rank": 1072,
                    "pct": 99,
                    "higher_than": 143209,
                },
                "similar_age_journal_3m": {
                    "count": 877,
                    "mean": 51.69187913340936,
                    "rank": 71,
                    "pct": 91,
                    "higher_than": 806,
                },
            },
            "authors": [],
            "type": "news",
            "handles": [],
            "pubdate": 1313884800,
            "epubdate": 1313884800,
            "dimensions_publication_id": "pub.1056456446",
            "altmetric_id": 241939,
            "schema": "1.5.4",
            "is_oa": False,
            "cited_by_fbwalls_count": 5,
            "cited_by_feeds_count": 3,
            "cited_by_msm_count": 1,
            "cited_by_posts_count": 157,
            "cited_by_rdts_count": 1,
            "cited_by_tweeters_count": 138,
            "cited_by_accounts_count": 148,
            "last_updated": 1334237127,
            "score": 140.5,
            "history": {
                "1y": 0,
                "6m": 0,
                "3m": 0,
                "1m": 0,
                "1w": 0,
                "6d": 0,
                "5d": 0,
                "4d": 0,
                "3d": 0,
                "2d": 0,
                "1d": 0,
                "at": 140.5,
            },
            "url": "http://dx.doi.org/10.1038/news.2011.490",
            "added_on": 1313946657,
            "published_on": 1313884800,
            "subjects": ["science"],
            "scopus_subjects": ["General"],
            "readers": {"citeulike": "0", "mendeley": "9", "connotea": "0"},
            "readers_count": 9,
            "images": {
                "small": "https://badges.altmetric.com/?size=64&score=141&types=mbrttttf",
                "medium": "https://badges.altmetric.com/?size=100&score=141&types=mbrttttf",
                "large": "https://badges.altmetric.com/?size=180&score=141&types=mbrttttf",
            },
            "details_url": "https://www.altmetric.com/details.php?citation_id=241939",
        }

    def test_map_metrics_with_complete_data(self):
        """
        Test mapping with all fields present.
        """
        # Act
        result = AltmetricMapper().map_metrics(self.sample_response)

        # Assert
        self.assertEqual(result["altmetric_id"], 241939)
        self.assertEqual(result["facebook_count"], 5)
        self.assertEqual(result["twitter_count"], 138)
        self.assertEqual(result["bluesky_count"], 0)
        self.assertEqual(result["score"], 140.5)
        self.assertEqual(
            result["last_updated"], datetime.fromtimestamp(1334237127, tz=timezone.utc)
        )

    def test_map_metrics_with_missing_counts(self):
        """
        Test mapping when social media counts are missing.
        """
        # Arrange
        minimal_response = {
            "altmetric_id": 241939,
            "score": 140.5,
            "last_updated": 1334237127,
        }

        # Act
        result = AltmetricMapper().map_metrics(minimal_response)

        # Assert
        self.assertEqual(result["altmetric_id"], 241939)
        self.assertEqual(result["facebook_count"], 0)
        self.assertEqual(result["twitter_count"], 0)
        self.assertEqual(result["bluesky_count"], 0)
        self.assertEqual(result["score"], 140.5)

    def test_map_metrics_with_missing_timestamp(self):
        """
        Test mapping when last_updated is missing.
        """
        # Arrange
        response_without_timestamp = {
            "altmetric_id": 241939,
            "cited_by_fbwalls_count": 5,
        }

        # Act
        result = AltmetricMapper().map_metrics(response_without_timestamp)

        # Assert
        self.assertIsNone(result["last_updated"])

    def test_map_metrics_with_empty_record(self):
        """
        Test mapping with None or empty dict.
        """
        # Act
        result = AltmetricMapper().map_metrics(None)

        # Assert
        self.assertEqual(result, {})

    def test_map_metrics_timestamp_conversion(self):
        """
        Test Unix timestamp conversion to datetime.
        """
        # Arrange
        response = {
            "altmetric_id": 241939,
            "last_updated": 1334237127,
        }

        # Act
        result = AltmetricMapper().map_metrics(response)

        # Assert
        expected_datetime = datetime.fromtimestamp(1334237127, tz=timezone.utc)
        self.assertEqual(result["last_updated"], expected_datetime)
        self.assertIsInstance(result["last_updated"], datetime)

    def test_map_metrics_string_timestamp(self):
        """
        Test that string timestamps are properly converted.
        Real-world case from DOI 10.1146/annurev-clinpsy-032813-153716.
        """
        # Arrange
        response = {
            "altmetric_id": 241939,
            "last_updated": "1757512900",  # String instead of int
        }

        # Act
        result = AltmetricMapper().map_metrics(response)

        # Assert
        expected_datetime = datetime.fromtimestamp(1757512900, tz=timezone.utc)
        self.assertEqual(result["last_updated"], expected_datetime)
        self.assertIsInstance(result["last_updated"], datetime)

    def test_map_metrics_invalid_timestamp(self):
        """
        Test that invalid timestamps return None instead of crashing.
        """
        # Arrange
        response = {
            "altmetric_id": 241939,
            "last_updated": "invalid",
        }

        # Act
        result = AltmetricMapper().map_metrics(response)

        # Assert
        self.assertIsNone(result["last_updated"])

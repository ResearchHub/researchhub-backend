"""Tests for XMapper."""

from datetime import datetime, timezone
from unittest import TestCase

from paper.ingestion.mappers.enrichment.x import XMapper


class XMapperTest(TestCase):
    """Test cases for XMapper."""

    def setUp(self):
        self.mapper = XMapper()

    def test_map_to_x_post_basic(self):
        """Test mapping basic post data."""
        post_data = {
            "id": "1234567890",
            "text": "This is a test post about a paper",
            "author_id": "author123",
            "created_at": "2024-01-15T10:30:00.000Z",
            "like_count": 10,
            "repost_count": 5,
            "reply_count": 2,
            "quote_count": 1,
            "impression_count": 100,
        }

        result = self.mapper.map_to_x_post(post_data)

        self.assertIsNotNone(result)
        self.assertEqual(result.post_id, "1234567890")
        self.assertEqual(result.text, "This is a test post about a paper")
        self.assertEqual(result.author_id, "author123")
        self.assertIsNotNone(result.posted_date)
        self.assertEqual(result.posted_date.year, 2024)
        self.assertEqual(result.posted_date.month, 1)
        self.assertEqual(result.posted_date.day, 15)
        self.assertEqual(result.like_count, 10)
        self.assertEqual(result.repost_count, 5)
        self.assertEqual(result.reply_count, 2)
        self.assertEqual(result.quote_count, 1)
        self.assertEqual(result.impression_count, 100)

    def test_map_to_x_post_missing_id_returns_none(self):
        """Test that missing id returns None."""
        post_data = {
            "text": "Test post without id",
            "author_id": "author123",
        }

        result = self.mapper.map_to_x_post(post_data)

        self.assertIsNone(result)

    def test_map_to_x_post_empty_id_returns_none(self):
        """Test that empty string id returns None."""
        post_data = {
            "id": "",
            "text": "Test post with empty id",
        }

        result = self.mapper.map_to_x_post(post_data)

        self.assertIsNone(result)

    def test_map_to_x_post_missing_optional_fields(self):
        """Test mapping with missing optional fields uses defaults."""
        post_data = {
            "id": "9876543210",
            "created_at": "2024-01-15T10:30:00Z",
        }

        result = self.mapper.map_to_x_post(post_data)

        self.assertIsNotNone(result)
        self.assertEqual(result.post_id, "9876543210")
        self.assertIsNone(result.author_id)
        self.assertEqual(result.text, "")
        self.assertIsNotNone(result.posted_date)
        self.assertEqual(result.like_count, 0)
        self.assertEqual(result.repost_count, 0)
        self.assertEqual(result.reply_count, 0)
        self.assertEqual(result.quote_count, 0)
        self.assertEqual(result.impression_count, 0)

    def test_map_to_x_posts_empty_list(self):
        """Test mapping empty list returns empty list."""
        result = self.mapper.map_to_x_posts([])

        self.assertEqual(result, [])

    def test_map_to_x_posts_multiple(self):
        """Test mapping multiple posts."""
        posts_data = [
            {
                "id": "111",
                "text": "First post",
                "created_at": "2024-01-15T10:30:00Z",
                "like_count": 5,
            },
            {
                "id": "222",
                "text": "Second post",
                "created_at": "2024-01-16T10:30:00Z",
                "like_count": 10,
            },
            {
                "id": "333",
                "text": "Third post",
                "created_at": "2024-01-17T10:30:00Z",
                "like_count": 15,
            },
        ]

        result = self.mapper.map_to_x_posts(posts_data)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].post_id, "111")
        self.assertEqual(result[0].text, "First post")
        self.assertEqual(result[0].like_count, 5)
        self.assertEqual(result[1].post_id, "222")
        self.assertEqual(result[1].text, "Second post")
        self.assertEqual(result[1].like_count, 10)
        self.assertEqual(result[2].post_id, "333")
        self.assertEqual(result[2].text, "Third post")
        self.assertEqual(result[2].like_count, 15)

    def test_map_to_x_posts_filters_invalid(self):
        """Test that invalid posts (missing id) are filtered out."""
        posts_data = [
            {"id": "111", "text": "Valid post", "created_at": "2024-01-15T10:30:00Z"},
            {"text": "Missing id", "created_at": "2024-01-15T10:30:00Z"},
            {
                "id": "333",
                "text": "Another valid post",
                "created_at": "2024-01-15T10:30:00Z",
            },
            {"id": "", "text": "Empty id", "created_at": "2024-01-15T10:30:00Z"},
        ]

        result = self.mapper.map_to_x_posts(posts_data)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].post_id, "111")
        self.assertEqual(result[1].post_id, "333")

    def test_extract_metrics_empty_list(self):
        """Test extract_metrics with empty list returns zeros."""
        result = self.mapper.extract_metrics([])

        self.assertEqual(result["post_count"], 0)
        self.assertEqual(result["total_likes"], 0)
        self.assertEqual(result["total_reposts"], 0)
        self.assertEqual(result["total_replies"], 0)
        self.assertEqual(result["total_quotes"], 0)
        self.assertEqual(result["total_impressions"], 0)

    def test_extract_metrics_aggregates_correctly(self):
        """Test extract_metrics aggregates metrics from multiple posts."""
        posts = [
            {
                "id": "1",
                "like_count": 10,
                "repost_count": 5,
                "reply_count": 2,
                "quote_count": 1,
                "impression_count": 100,
            },
            {
                "id": "2",
                "like_count": 20,
                "repost_count": 10,
                "reply_count": 5,
                "quote_count": 2,
                "impression_count": 200,
            },
            {
                "id": "3",
                "like_count": 30,
                "repost_count": 15,
                "reply_count": 8,
                "quote_count": 3,
                "impression_count": 300,
            },
        ]

        result = self.mapper.extract_metrics(posts)

        self.assertEqual(result["post_count"], 3)
        self.assertEqual(result["total_likes"], 60)
        self.assertEqual(result["total_reposts"], 30)
        self.assertEqual(result["total_replies"], 15)
        self.assertEqual(result["total_quotes"], 6)
        self.assertEqual(result["total_impressions"], 600)

    def test_extract_metrics_handles_missing_fields(self):
        """Test extract_metrics handles posts with missing metric fields."""
        posts = [
            {"id": "1", "like_count": 10},
            {"id": "2"},
        ]

        result = self.mapper.extract_metrics(posts)

        self.assertEqual(result["post_count"], 2)
        self.assertEqual(result["total_likes"], 10)
        self.assertEqual(result["total_reposts"], 0)
        self.assertEqual(result["total_replies"], 0)
        self.assertEqual(result["total_quotes"], 0)
        self.assertEqual(result["total_impressions"], 0)

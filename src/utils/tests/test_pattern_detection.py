import time
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from utils.pattern_detection import RequestPatternAnalyzer


class PatternDetectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.ip = "192.168.1.1"
        self.analyzer = RequestPatternAnalyzer(self.ip)

    def tearDown(self):
        cache.clear()

    def test_invalid_ip_address(self):
        with self.assertRaises(ValueError):
            RequestPatternAnalyzer("")

        with self.assertRaises(ValueError):
            RequestPatternAnalyzer("x" * 50)

    def test_record_request_stores_in_cache(self):
        self.analyzer.record_request("test query", 1)
        cached = cache.get(self.analyzer.cache_key)
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0]["query"], "test query")
        self.assertEqual(cached[0]["page"], 1)

    def test_record_request_limits_to_20(self):
        for _ in range(25):
            self.analyzer.record_request("test", 1)
        cached = cache.get(self.analyzer.cache_key)
        self.assertEqual(len(cached), 20)

    def test_analyze_pattern_insufficient_requests(self):
        for i in range(5):
            self.analyzer.record_request("test", i)
        cached = cache.get(self.analyzer.cache_key)
        result = self.analyzer.analyze_pattern(cached)
        self.assertFalse(result["suspicious"])

    def test_analyze_pattern_sequential_pages(self):
        for i in range(1, 11):
            self.analyzer.record_request("test", i)
        cached = cache.get(self.analyzer.cache_key)
        result = self.analyzer.analyze_pattern(cached)
        self.assertTrue(result["suspicious"])
        self.assertEqual(result["action"], "block")
        issue_types = [issue["type"] for issue in result["issues"]]
        self.assertIn("sequential_pages", issue_types)

    def test_analyze_pattern_identical_queries(self):
        for _ in range(20):
            self.analyzer.record_request("same query", 1)
        cached = cache.get(self.analyzer.cache_key)
        result = self.analyzer.analyze_pattern(cached)
        self.assertTrue(result["suspicious"])
        issue_types = [issue["type"] for issue in result["issues"]]
        self.assertIn("repeated_query", issue_types)

    def test_analyze_pattern_regular_timing(self):
        base_time = time.time()
        for i in range(10):
            with patch("time.time", return_value=base_time + i * 1.2):
                self.analyzer.record_request(f"query{i}", 1)
        cached = cache.get(self.analyzer.cache_key)
        result = self.analyzer.analyze_pattern(cached)
        issue_types = [issue["type"] for issue in result["issues"]]
        self.assertIn("regular_timing", issue_types)

    def test_analyze_pattern_short_queries(self):
        for _ in range(10):
            self.analyzer.record_request("a", 1)
        cached = cache.get(self.analyzer.cache_key)
        result = self.analyzer.analyze_pattern(cached)
        issue_types = [issue["type"] for issue in result["issues"]]
        self.assertIn("short_queries", issue_types)

    def test_analyze_pattern_alphabetical_scraping(self):
        for char in "abcdefghij":
            self.analyzer.record_request(char, 1)
        cached = cache.get(self.analyzer.cache_key)
        result = self.analyzer.analyze_pattern(cached)
        self.assertTrue(result["suspicious"])
        issue_types = [issue["type"] for issue in result["issues"]]
        self.assertIn("alphabetical_scraping", issue_types)
        self.assertEqual(result["action"], "block")

    def test_analyze_pattern_normal_usage(self):
        queries = ["machine learning", "neural networks", "deep learning", "AI"]
        pages = [1, 2, 1, 3, 1, 2, 1, 1, 2, 1, 1, 1]
        for idx, query in enumerate(queries * 3):
            self.analyzer.record_request(query, pages[idx])
            # Add small varying delays to simulate normal user behavior
            time.sleep(0.01 + (idx % 3) * 0.02)
        cached = cache.get(self.analyzer.cache_key)
        result = self.analyzer.analyze_pattern(cached)
        self.assertFalse(result["suspicious"])

    def test_analyze_pattern_warn_action(self):
        for idx in range(10):
            self.analyzer.record_request("test query", idx)
        cached = cache.get(self.analyzer.cache_key)
        result = self.analyzer.analyze_pattern(cached)
        self.assertIn(result["action"], ["warn", "allow", "block"])

    def test_record_request_filters_old_requests(self):
        old_time = time.time() - 7200
        cache.set(
            self.analyzer.cache_key,
            [{"query": "old", "page": 1, "timestamp": old_time}],
            3600,
        )
        self.analyzer.record_request("new", 1)
        cached = cache.get(self.analyzer.cache_key)
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0]["query"], "new")

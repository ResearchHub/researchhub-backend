"""
Request pattern detection for identifying bot behavior.

Tracks request history per IP and analyzes patterns:
- Sequential page access (page 1, 2, 3, 4...)
- Identical query repetition
- Mechanical timing (low variance)
- Systematic query variations
"""

import logging
import time
from typing import Any, Dict, List

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Pattern detection thresholds
MIN_REQUESTS_FOR_ANALYSIS = 10
SEQUENTIAL_PAGE_THRESHOLD = 5  # Pages in sequence to flag
IDENTICAL_QUERY_THRESHOLD = 15  # Same query repeated
TIMING_VARIANCE_THRESHOLD = 0.1  # Low variance = robotic
SHORT_QUERY_RATIO_THRESHOLD = 0.7  # 70% of queries are 1-2 chars


class RequestPatternAnalyzer:
    """
    Analyzes request patterns to detect bot behavior.
    Tracks request history per IP in Redis cache.
    """

    def __init__(self, ip_address: str):
        if not ip_address or len(ip_address) > 45:
            raise ValueError("Invalid IP address")
        self.ip = ip_address
        self.cache_key_prefix = f"search:pattern:{ip_address}"
        self.cache_key = f"{self.cache_key_prefix}:requests"
        self.history_ttl = 3600

    def record_request(self, query: str, page: int) -> Dict[str, Any]:
        """
        Record a search request and return pattern analysis.
        Returns dict with 'suspicious', 'issues', 'score', and 'action' fields.
        """
        # Get existing requests
        requests = cache.get(self.cache_key, [])

        # Add new request
        requests.append(
            {
                "query": query,
                "page": page,
                "timestamp": time.time(),
            }
        )

        # Keep only last 20 requests
        requests = requests[-20:]

        # Filter to last hour
        one_hour_ago = time.time() - 3600
        requests = [r for r in requests if r["timestamp"] > one_hour_ago]

        # Save back to cache
        cache.set(self.cache_key, requests, self.history_ttl)

        # Analyze pattern
        return self.analyze_pattern(requests)

    def _check_sequential_pages(self, pages: List[int]) -> dict | None:
        if len(pages) < MIN_REQUESTS_FOR_ANALYSIS:
            return None
        is_sequential = all(
            pages[i] <= pages[i + 1] for i in range(len(pages) - 1)
        )
        if is_sequential:
            page_range = max(pages) - min(pages)
            if page_range >= SEQUENTIAL_PAGE_THRESHOLD:
                return {
                    "type": "sequential_pages",
                    "severity": "high",
                    "details": f"Pages {min(pages)}-{max(pages)} accessed sequentially",
                }
        return None

    def _check_identical_queries(self, queries: List[str]) -> dict | None:
        unique_queries = len(set(queries))
        if len(queries) >= IDENTICAL_QUERY_THRESHOLD and unique_queries == 1:
            return {
                "type": "repeated_query",
                "severity": "high",
                "details": f"Same query repeated {len(queries)} times",
            }
        return None

    def _check_regular_timing(self, timestamps: List[float]) -> dict | None:
        if len(timestamps) < MIN_REQUESTS_FOR_ANALYSIS:
            return None
        intervals = [
            timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)
        ]
        if not intervals:
            return None
        avg_interval = sum(intervals) / len(intervals)
        variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
        if variance < TIMING_VARIANCE_THRESHOLD and avg_interval > 0:
            return {
                "type": "regular_timing",
                "severity": "medium",
                "details": f"Requests every {avg_interval:.1f}s with low variance ({variance:.3f})",
            }
        return None

    def _check_short_queries(self, queries: List[str]) -> dict | None:
        if len(queries) < MIN_REQUESTS_FOR_ANALYSIS:
            return None
        short_queries = sum(1 for q in queries if len(q) <= 2)
        if short_queries / len(queries) > SHORT_QUERY_RATIO_THRESHOLD:
            return {
                "type": "short_queries",
                "severity": "medium",
                "details": f"{short_queries}/{len(queries)} queries are 1-2 chars",
            }
        return None

    def _check_alphabetical_scraping(self, queries: List[str]) -> dict | None:
        if len(queries) < MIN_REQUESTS_FOR_ANALYSIS:
            return None
        single_char_queries = [q for q in queries if len(q) == 1]
        if len(single_char_queries) >= 5:
            is_alphabetical = all(
                ord(single_char_queries[i]) <= ord(single_char_queries[i + 1])
                for i in range(len(single_char_queries) - 1)
            )
            if is_alphabetical:
                return {
                    "type": "alphabetical_scraping",
                    "severity": "critical",
                    "details": "Queries follow alphabetical pattern",
                }
        return None

    def analyze_pattern(self, requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        if len(requests) < MIN_REQUESTS_FOR_ANALYSIS:
            return {"suspicious": False, "reason": None, "score": 0.0, "action": "allow"}

        queries = [r["query"] for r in requests]
        pages = [r["page"] for r in requests]
        timestamps = [r["timestamp"] for r in requests]

        issues = []
        severity_scores = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.2}

        issue = self._check_sequential_pages(pages)
        if issue:
            issues.append(issue)

        issue = self._check_identical_queries(queries)
        if issue:
            issues.append(issue)

        issue = self._check_regular_timing(timestamps)
        if issue:
            issues.append(issue)

        issue = self._check_short_queries(queries)
        if issue:
            issues.append(issue)

        issue = self._check_alphabetical_scraping(queries)
        if issue:
            issues.append(issue)

        suspicion_score = sum(
            severity_scores.get(i["severity"], 0.2) for i in issues
        )
        suspicion_score = min(suspicion_score, 1.0)

        if suspicion_score > 0.7:
            action = "block"
        elif suspicion_score > 0.4:
            action = "warn"
        else:
            action = "allow"

        return {
            "suspicious": len(issues) > 0,
            "issues": issues,
            "score": suspicion_score,
            "action": action,
        }


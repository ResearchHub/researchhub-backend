from django.test import TestCase
from rest_framework.test import APIRequestFactory

from utils.search_throttles import (
    SearchAnonBurstThrottle,
    SearchAnonDailyThrottle,
    SearchAnonRateThrottle,
    SearchUserRateThrottle,
)


class SearchThrottleTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.request = self.factory.get("/api/search/", {"q": "test"})
        self.view = None

    def test_search_anon_burst_throttle_scope(self):
        throttle = SearchAnonBurstThrottle()
        self.assertEqual(throttle.scope, "search_anon_burst")
        self.assertEqual(throttle.rate, "5/second")

    def test_search_anon_rate_throttle_scope(self):
        throttle = SearchAnonRateThrottle()
        self.assertEqual(throttle.scope, "search_anon")
        self.assertEqual(throttle.rate, "20/minute")

    def test_search_anon_daily_throttle_scope(self):
        throttle = SearchAnonDailyThrottle()
        self.assertEqual(throttle.scope, "search_anon_daily")
        self.assertEqual(throttle.rate, "500/day")

    def test_search_user_rate_throttle_scope(self):
        throttle = SearchUserRateThrottle()
        self.assertEqual(throttle.scope, "search_user")
        self.assertEqual(throttle.rate, "100/minute")


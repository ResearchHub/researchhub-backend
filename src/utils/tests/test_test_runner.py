import io
import unittest
from types import SimpleNamespace

from django.core.cache import cache
from django.test import RequestFactory
from rest_framework.throttling import AnonRateThrottle

from utils.test_runner import IsolatedCacheRunner, IsolatedRemoteRunner


class CacheIsolationRunnerTests(unittest.TestCase):
    def _runners(self):
        yield unittest.TextTestRunner(
            stream=io.StringIO(),
            resultclass=IsolatedCacheRunner().get_resultclass(),
        )
        yield IsolatedRemoteRunner()

    def test_cache_and_throttles_work_within_tests_but_do_not_leak(self):
        # Arrange: both tests use the same IP and cache keys.
        class RequestTest(unittest.TestCase):
            def test_request(self):
                self.assertIsNone(cache.get("runner-isolation"))
                cache.set("runner-isolation", "present")
                self.assertEqual(cache.get("runner-isolation"), "present")
                request = RequestFactory().get("/api/leaderboard/reviewers/")
                request.user = SimpleNamespace(is_authenticated=False)
                for _ in range(50):
                    self.assertTrue(AnonRateThrottle().allow_request(request, None))
                self.assertFalse(AnonRateThrottle().allow_request(request, None))

        for runner in self._runners():
            with self.subTest(runner=type(runner).__name__):
                cache.set("runner-isolation", "left by an earlier test")

                # Act
                result = runner.run(
                    unittest.TestSuite(
                        [RequestTest("test_request"), RequestTest("test_request")]
                    )
                )

                # Assert
                if hasattr(result, "events"):
                    failures = [
                        event
                        for event in result.events
                        if event[0] in ("addError", "addFailure")
                    ]
                    self.assertEqual(failures, [])
                else:
                    self.assertTrue(result.wasSuccessful(), str(result))
                self.assertEqual(result.testsRun, 2)
                self.assertIsNone(cache.get("runner-isolation"))

    def test_cache_is_cleared_after_setup_failure(self):
        # Arrange
        class BrokenSetupTest(unittest.TestCase):
            def setUp(self):
                cache.set("runner-isolation", "left by failed setup")
                raise RuntimeError("setup failed")

            def test_request(self):
                pass

        for runner in self._runners():
            with self.subTest(runner=type(runner).__name__):
                # Act
                result = runner.run(
                    unittest.TestSuite([BrokenSetupTest("test_request")])
                )

                # Assert: remote results store errors as events.
                self.assertEqual(result.testsRun, 1)
                if hasattr(result, "events"):
                    self.assertTrue(
                        any(event[0] == "addError" for event in result.events)
                    )
                else:
                    self.assertEqual(len(result.errors), 1)
                self.assertIsNone(cache.get("runner-isolation"))

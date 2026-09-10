"""Isolate the in-memory test cache between tests, including parallel workers."""

import unittest

from django.core.cache import cache
from django.test.runner import (
    DiscoverRunner,
    ParallelTestSuite,
    RemoteTestResult,
    RemoteTestRunner,
)


class CacheIsolationMixin:
    def startTest(self, test):  # noqa: N802 - unittest hook
        cache.clear()
        super().startTest(test)

    def stopTest(self, test):  # noqa: N802 - unittest hook
        try:
            super().stopTest(test)
        finally:
            cache.clear()


class IsolatedRemoteResult(CacheIsolationMixin, RemoteTestResult):
    pass


class IsolatedRemoteRunner(RemoteTestRunner):
    resultclass = IsolatedRemoteResult


class IsolatedParallelSuite(ParallelTestSuite):
    runner_class = IsolatedRemoteRunner


class IsolatedCacheRunner(DiscoverRunner):
    parallel_test_suite = IsolatedParallelSuite

    def get_resultclass(self):
        base = super().get_resultclass() or unittest.TextTestResult

        class IsolatedResult(CacheIsolationMixin, base):
            pass

        return IsolatedResult

"""Test runner: create DB extensions and isolate the in-memory cache between tests."""

import unittest

from django.apps import apps
from django.contrib.postgres.operations import HStoreExtension
from django.core.cache import cache
from django.db import connections
from django.db.models.signals import pre_migrate
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


def create_extensions(sender, using, **kwargs):
    # Only a migration creates hstore, so a test DB built from models needs it here.
    with connections[using].schema_editor() as schema_editor:
        HStoreExtension().database_forwards(sender.label, schema_editor, None, None)


class IsolatedCacheRunner(DiscoverRunner):
    parallel_test_suite = IsolatedParallelSuite

    def setup_databases(self, **kwargs):
        sender = apps.get_app_config("notification")
        pre_migrate.connect(create_extensions, sender=sender)
        try:
            return super().setup_databases(**kwargs)
        finally:
            pre_migrate.disconnect(create_extensions, sender=sender)

    def get_resultclass(self):
        base = super().get_resultclass() or unittest.TextTestResult

        class IsolatedResult(CacheIsolationMixin, base):
            pass

        return IsolatedResult

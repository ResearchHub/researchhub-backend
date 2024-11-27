from unittest import TestCase
from unittest.mock import Mock, patch

from django_elasticsearch_dsl.registries import registry

from search.celery import (  # Replace `search.celery` with the actual module name
    DEBOUNCE_PERIOD,
    CelerySignalProcessor,
)


class TestCelerySignalProcessor(TestCase):
    def setUp(self):
        self.instance = Mock()
        self.instance.pk = 1
        self.instance._meta.app_label = "test_app"
        self.instance._meta.concrete_model = Mock()
        self.instance._meta.concrete_model.__name__ = "TestModel"

    @patch("search.celery.CelerySignalProcessor.registry_update_task.apply_async")
    @patch("search.celery.cache")
    def test_handle_save_registry_model(self, cache_mock, apply_async_mock):
        """
        Verifies that the task is triggered.
        """

        # Arrange
        cache_mock.get.return_value = False  # cache miss

        # Act
        with patch.object(registry, "_models", {self.instance._meta.concrete_model}):
            processor = CelerySignalProcessor(registry)
            processor.handle_save(None, self.instance)

        # Assert
        cache_mock.get.assert_called_once_with(
            "registry_update_task_test_app_TestModel_1"
        )
        apply_async_mock.assert_called_once_with(
            (1, "test_app", "TestModel"), countdown=DEBOUNCE_PERIOD
        )
        cache_mock.set.assert_called_once_with(
            "registry_update_task_test_app_TestModel_1", True, timeout=DEBOUNCE_PERIOD
        )

    @patch("search.celery.CelerySignalProcessor.registry_update_task.apply_async")
    @patch("search.celery.cache")
    def test_debounce_registry_update_task(self, cache_mock, apply_async_mock):
        """
        Verifies that the task is not triggered due to debouncing.
        """

        # Arrange
        cache_mock.get.return_value = True  # cache hit

        # Act
        with patch.object(registry, "_models", {self.instance._meta.concrete_model}):
            processor = CelerySignalProcessor(registry)
            processor.handle_save(None, self.instance)

        # Assert
        cache_mock.get.assert_called_once_with(
            "registry_update_task_test_app_TestModel_1"
        )
        apply_async_mock.assert_not_called()  # Task should not be triggered
        cache_mock.set.assert_not_called()  # Cache should not be updated

    @patch(
        "search.celery.CelerySignalProcessor.registry_update_related_task.apply_async"
    )
    @patch("search.celery.cache")
    def test_handle_save_related_model(self, cache_mock, apply_async_mock):
        """
        Verifies that the related task is triggered.
        """

        # Arrange
        cache_mock.get.return_value = False  # cache miss
        cache_mock.set = Mock()

        # Act
        with patch.object(
            registry, "_related_models", {self.instance._meta.concrete_model}
        ):
            processor = CelerySignalProcessor(registry)
            processor.handle_save(None, self.instance)

        cache_mock.get.assert_called_once_with(
            "registry_update_related_task_test_app_TestModel_1"
        )
        apply_async_mock.assert_called_once_with(
            (1, "test_app", "TestModel"), countdown=DEBOUNCE_PERIOD
        )
        cache_mock.set.assert_called_once_with(
            "registry_update_related_task_test_app_TestModel_1",
            True,
            timeout=DEBOUNCE_PERIOD,
        )

    @patch("search.celery.registry.update")
    @patch("search.celery.apps.get_model")
    def test_registry_update_task_success(self, get_model_mock, registry_update_mock):
        # Arrange
        model_mock = Mock()
        model_mock.objects.get.return_value = self.instance
        get_model_mock.return_value = model_mock

        # Act
        CelerySignalProcessor.registry_update_task(1, "test_app", "TestModel")

        # Assert
        get_model_mock.assert_called_once_with("test_app", "TestModel")
        model_mock.objects.get.assert_called_once_with(pk=1)
        registry_update_mock.assert_called_once_with(self.instance)

    @patch("search.celery.sentry.log_error")
    @patch("search.celery.apps.get_model", side_effect=LookupError("Model not found"))
    def test_registry_update_task_lookup_error(self, get_model_mock, log_error_mock):
        # Act
        CelerySignalProcessor.registry_update_task(1, "test_app", "NonExistentModel")

        # Assert
        get_model_mock.assert_called_once_with("test_app", "NonExistentModel")
        log_error_mock.assert_called_once()

    @patch("search.celery.apps.get_model")
    def test_registry_update_task_does_not_exist(self, get_model_mock):
        # Arrange
        model_mock = Mock()
        model_mock.objects.get.side_effect = model_mock.DoesNotExist
        get_model_mock.return_value = model_mock

        # Act
        CelerySignalProcessor.registry_update_task(1, "test_app", "TestModel")

        # Assert
        get_model_mock.assert_called_once_with("test_app", "TestModel")
        model_mock.objects.get.assert_called_once_with(pk=1)

    @patch("search.celery.registry.update_related")
    @patch("search.celery.apps.get_model")
    def test_registry_update_related_task_success(
        self, get_model_mock, registry_update_related_mock
    ):
        # Arrange
        model_mock = Mock()
        model_mock.objects.get.return_value = self.instance
        get_model_mock.return_value = model_mock

        # Act
        CelerySignalProcessor.registry_update_related_task(1, "test_app", "TestModel")

        # Assert
        get_model_mock.assert_called_once_with("test_app", "TestModel")
        model_mock.objects.get.assert_called_once_with(pk=1)
        registry_update_related_mock.assert_called_once_with(self.instance)

    @patch("search.celery.sentry.log_error")
    @patch("search.celery.apps.get_model", side_effect=LookupError("Model not found"))
    def test_registry_update_related_task_lookup_error(
        self, get_model_mock, log_error_mock
    ):
        # Act
        CelerySignalProcessor.registry_update_related_task(
            1, "test_app", "NonExistentModel"
        )

        # Assert
        get_model_mock.assert_called_once_with("test_app", "NonExistentModel")
        log_error_mock.assert_called_once()

    @patch("search.celery.apps.get_model")
    def test_registry_update_related_task_does_not_exist(self, get_model_mock):
        # Arrange
        model_mock = Mock()
        model_mock.objects.get.side_effect = model_mock.DoesNotExist
        get_model_mock.return_value = model_mock

        # Act
        CelerySignalProcessor.registry_update_related_task(1, "test_app", "TestModel")

        # Assert
        get_model_mock.assert_called_once_with("test_app", "TestModel")
        model_mock.objects.get.assert_called_once_with(pk=1)

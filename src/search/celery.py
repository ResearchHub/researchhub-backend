import logging

from celery import shared_task
from django.apps import apps
from django.core.cache import cache
from django.db import transaction
from django_opensearch_dsl.registries import registry
from django_opensearch_dsl.signals import RealTimeSignalProcessor

# The debounce period in seconds
DEBOUNCE_PERIOD = 10


logger = logging.getLogger(__name__)


class CelerySignalProcessor(RealTimeSignalProcessor):
    def handle_save(self, sender, instance, **kwargs):
        pk = instance.pk
        app_label = instance._meta.app_label
        model = instance._meta.concrete_model
        model_name = model.__name__

        if model in registry._models:
            cache_key = f"registry_update_task_{app_label}_{model_name}_{pk}"
            if not cache.get(cache_key):
                transaction.on_commit(
                    lambda: self.registry_update_task.apply_async(
                        (pk, app_label, model_name), countdown=DEBOUNCE_PERIOD
                    )
                )
                # Add cache entry to prevent duplicate tasks within debounce period
                cache.set(cache_key, True, timeout=DEBOUNCE_PERIOD)

        if model in registry._related_models:
            cache_key = f"registry_update_related_task_{app_label}_{model_name}_{pk}"
            if not cache.get(cache_key):
                transaction.on_commit(
                    lambda: self.registry_update_related_task.apply_async(
                        (pk, app_label, model_name), countdown=DEBOUNCE_PERIOD
                    )
                )
                # Add cache entry to prevent duplicate tasks within debounce period
                cache.set(cache_key, True, timeout=DEBOUNCE_PERIOD)

    @shared_task(ignore_result=True)
    def registry_update_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
            instance = model.objects.get(pk=pk)
            registry.update(instance)
        except LookupError as e:
            logger.error("Failed to get model for update task: %s", e)
        except model.DoesNotExist:
            # Instance was deleted before it could be updated.
            logger.warning(
                "Instance=%s of model=%s.%s does not exist for update task",
                pk,
                app_label,
                model_name,
            )

    @shared_task(ignore_result=True)
    def registry_update_related_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
            instance = model.objects.get(pk=pk)
            registry.update_related(instance)
        except LookupError as e:
            logger.error("Failed to get model for update related task: %s", e)
        except model.DoesNotExist:
            # Instance was deleted before it could be updated.
            logger.warning(
                "Instance=%s of model=%s.%s does not exist for update related task",
                pk,
                app_label,
                model_name,
            )

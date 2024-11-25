from celery import shared_task
from django.apps import apps
from django.core.cache import cache
from django_elasticsearch_dsl.registries import registry
from django_elasticsearch_dsl.signals import RealTimeSignalProcessor

import utils.sentry as sentry

# The debounce period in seconds
DEBOUNCE_PERIOD = 10


class CelerySignalProcessor(RealTimeSignalProcessor):
    def handle_save(self, sender, instance, **kwargs):
        pk = instance.pk
        app_label = instance._meta.app_label
        model = instance._meta.concrete_model
        model_name = model.__name__

        if model in registry._models:
            cache_key = f"registry_update_task_{app_label}_{model_name}_{pk}"
            if not cache.get(cache_key):
                self.registry_update_task.apply_async(
                    (pk, app_label, model_name), countdown=DEBOUNCE_PERIOD
                )
                # Add cache entry to prevent duplicate tasks within debounce period
                cache.set(cache_key, True, timeout=DEBOUNCE_PERIOD)

        if model in registry._related_models:
            cache_key = f"registry_update_related_task_{app_label}_{model_name}_{pk}"
            if not cache.get(cache_key):
                self.registry_update_related_task.apply_async(
                    (pk, app_label, model_name), countdown=DEBOUNCE_PERIOD
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
            sentry.log_error(e)
        except model.DoesNotExist:
            # No-op: Instance was deleted before it could be updated.
            pass

    @shared_task(ignore_result=True)
    def registry_update_related_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
            instance = model.objects.get(pk=pk)
            registry.update_related(instance)
        except LookupError as e:
            sentry.log_error(e)
        except model.DoesNotExist:
            # No-op: Instance was deleted before it could be updated.
            pass

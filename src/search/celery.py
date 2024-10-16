from celery import shared_task
from django.apps import apps
from django.core.cache import cache
from django_elasticsearch_dsl.registries import registry
from django_elasticsearch_dsl.signals import RealTimeSignalProcessor

import utils.sentry as sentry

# Time in seconds to debounce signals for registry update tasks.
SIGNAL_DEBOUNCE_PERIOD = 5


class CelerySignalProcessor(RealTimeSignalProcessor):

    def handle_save(self, sender, instance, **kwargs):
        pk = instance.pk
        app_label = instance._meta.app_label
        model = instance._meta.concrete_model
        model_name = model.__name__

        cache_key = f"registry_update_task_{app_label}_{model_name}_{pk}"

        # Use cache to debounce update tasks for the same model instances
        if not cache.get(cache_key):
            cache.set(cache_key, True, timeout=SIGNAL_DEBOUNCE_PERIOD)

            if model in registry._models:
                self.registry_update_task.apply_async(
                    (pk, app_label, model_name), countdown=3
                )

            if model in registry._related_models:
                self.registry_update_related_task.apply_async(
                    (pk, app_label, model_name), countdown=3
                )

    @shared_task(ignore_result=True)
    def registry_update_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError as e:
            sentry.log_error(e)
            pass
        else:
            registry.update(model.objects.get(pk=pk))

    @shared_task(ignore_result=True)
    def registry_update_related_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError as e:
            sentry.log_error(e)
            pass
        else:
            registry.update_related(model.objects.get(pk=pk))

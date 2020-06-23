from django.apps import apps

from celery import shared_task
from django_elasticsearch_dsl.registries import registry
from django_elasticsearch_dsl.signals import (
    RealTimeSignalProcessor,
)

import utils.sentry as sentry


class CelerySignalProcessor(RealTimeSignalProcessor):

    def handle_save(self, sender, instance, **kwargs):
        pk = instance.pk
        app_label = instance._meta.app_label
        model_name = instance._meta.concrete_model.__name__

        self.registry_update_task.delay(pk, app_label, model_name)
        self.registry_update_related_task.delay(pk, app_label, model_name)

    @shared_task()
    def registry_update_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError as e:
            sentry.log_error(e)
            pass
        else:
            registry.update(
                model.objects.get(pk=pk)
            )

    @shared_task()
    def registry_update_related_task(pk, app_label, model_name):
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError as e:
            sentry.log_error(e)
            pass
        else:
            registry.update_related(
                model.objects.get(pk=pk)
            )

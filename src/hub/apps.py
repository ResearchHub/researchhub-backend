from django.apps import AppConfig


class HubConfig(AppConfig):
    name = 'hub'

    def ready(self):
        from .signals import update_paper_count_create  # noqa

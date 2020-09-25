from django.apps import AppConfig


class HubConfig(AppConfig):
    name = 'hub'

    def ready(self):
        import hub.signals  # noqa

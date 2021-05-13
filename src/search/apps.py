from django.apps import AppConfig


class SearchConfig(AppConfig):
    name = 'search'

    def ready(self):
        import search.signals  # noqa: F401

from django.apps import AppConfig


class SearchConfig(AppConfig):
    name = "search"

    def ready(self):
        import search.signals.user_events  # noqa: F401

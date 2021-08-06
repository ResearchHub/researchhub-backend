from django.apps import AppConfig


class HypothesisConfig(AppConfig):
    name = 'hypothesis'

    def ready(self):
        import hypothesis.signals

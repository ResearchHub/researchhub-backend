from django.apps import AppConfig


class PaperConfig(AppConfig):
    name = 'paper'

    def ready(self):
        import paper.signals

import os

from django.apps import AppConfig


class PaperConfig(AppConfig):
    name = 'paper'

    def ready(self):
        import paper.signals  # noqa

        if not os.path.isdir('/tmp/figures'):
            os.mkdir('/tmp/figures')

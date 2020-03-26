import os

from django.apps import AppConfig


class PaperConfig(AppConfig):
    name = 'paper'

    def ready(self):
        import paper.signals

        if not os.path.isdir('paper/figures'):
            os.mkdir('paper/figures')

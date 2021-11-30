from django.apps import AppConfig


class NoteConfig(AppConfig):
    name = 'note'

    def ready(self):
        import note.signals

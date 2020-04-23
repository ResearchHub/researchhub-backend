'''
Setting up watchdog watcher to read files from arxiv.
'''

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):

    def handle(self, *args, **options):
        patterns = "*"
        ignore_patterns = ""
        ignore_directories = False
        case_sensitive = True
        my_event_handler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
        my_event_handler.on_created = self.on_created

    def on_created(self, event):
        import pdb; pdb.set_trace()

'''
Setting up watchdog watcher to read files from arxiv.
'''

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from django.core.management.base import BaseCommand

from paper.models import Paper

class MyEventHandler(FileSystemEventHandler):
    def __init__(self, observer):
        self.observer = observer

    def on_created(self, event):
        """
        After a file is created, run processing on it
        """
        # TODO: Process the new file that came in
        # event.src_path gives you the path to the file and the file name as a string: i.e. './hello.py'
        # split this string to get the name of the event and then can run the metadata_parser on the file.

class Command(BaseCommand):

    def handle(self, *args, **options):
        path = '.' #TODO: Change this to the path we want to actually watch
        observer = Observer()
        event_handler = MyEventHandler(observer)
        observer.schedule(event_handler, path, recursive=True)
        observer.start()
        try:
            while observer.isAlive():
                observer.join(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    def on_created(self, event):
        import pdb; pdb.set_trace()

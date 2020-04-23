'''
Setting up watchdog watcher to read files from arxiv.
'''

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from django.core.management.base import BaseCommand

from utils.arxiv.metadata_parser import extract_xml_gzip, parse_arxiv_metadata


class MyEventHandler(FileSystemEventHandler):
    def __init__(self, observer):
        self.observer = observer

    def on_modified(self, event):
        """
        After a file is modified, run processing on it
        """
        print('MODIFIED')
        file_path = event.src_path
        print(file_path)
        if file_path.endswith('.xml.gz'):
            xml_path = extract_xml_gzip(file_path)
            metadata_records = parse_arxiv_metadata(xml_path)
            for record in metadata_records:
                try:
                    record.create_paper()
                except Exception as e:
                    print(e)


class Command(BaseCommand):

    def handle(self, *args, **options):
        path = '/tmp/preprints/arxiv/metadata'
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

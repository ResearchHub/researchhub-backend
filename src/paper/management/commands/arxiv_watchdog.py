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

    def on_created(self, event):
        file_path = event.src_path
        if file_path.endswith('.xml.gz') or file_path.endswith('.xml'):
            print('CREATED')
            print(file_path)

    def on_modified(self, event):
        """
        After a file is modified, run processing on it
        """
        file_path = event.src_path
        if file_path.endswith('.xml.gz'):
            print('MODIFIED')
            print(file_path)
            xml_path, extracted = extract_xml_gzip(file_path)
            metadata_records = parse_arxiv_metadata(xml_path)
            for record in metadata_records:
                try:
                    record.create_paper()
                except Exception as e:
                    print(e)


class Command(BaseCommand):
    help = 'Watches arxiv xml file changes to ingest arxiv papers'

    def add_arguments(self, parser):
        parser.add_argument('root', type=str, help='root directory name')

    def handle(self, *args, **options):
        path = f'/{options["root"]}/preprints/arxiv/metadata'
        observer = Observer()
        event_handler = MyEventHandler(observer)
        observer.schedule(event_handler, path, recursive=True)

        self.stdout.write(self.style.WARNING(f'Watching {path} ...'))
        observer.start()
        try:
            while observer.isAlive():
                observer.join(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

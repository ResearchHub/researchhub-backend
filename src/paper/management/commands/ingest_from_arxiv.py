'''
Setting up watchdog watcher to read files from arxiv.
'''

from django.core.management.base import BaseCommand

from utils.arxiv.metadata_parser import (
    extract_from_directory,
    parse_arxiv_metadata
)


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('root', type=str, help='root directory name')

    def handle(self, *args, **options):
        path = f'/{options["root"]}/preprints/arxiv/metadata'
        self.stdout.write(
            self.style.WARNING(f'Extracting xml files from {path} ...')
        )
        xml_files = extract_from_directory(path)
        for file in xml_files:
            records = parse_arxiv_metadata(file)
            for record in records:
                print('Creating paper for arxiv record', record.raw_arxiv_id)
                record.create_paper()

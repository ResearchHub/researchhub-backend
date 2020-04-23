'''
Setting up watchdog watcher to read files from arxiv.
'''

from django.core.management.base import BaseCommand

from utils.arxiv.metadata_parser import (
    extract_from_directory,
    parse_arxiv_metadata
)


class Command(BaseCommand):

    def handle(self, *args, **options):
        xml_files = extract_from_directory('/tmp/preprints/arxiv/metadata')
        for file in xml_files:
            records = parse_arxiv_metadata(file)
            for record in records:
                record.create_paper()

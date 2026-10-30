from django.core.management.base import BaseCommand, CommandError

from paper.ingestion.services.osf_registration_service import OSFRegistrationService
from utils.doi import DOI


class Command(BaseCommand):
    help = "Import OSF registrations (e.g. Lifecycle Journal submissions) by DOI"

    def add_arguments(self, parser):
        parser.add_argument(
            "dois",
            nargs="+",
            help="OSF registration DOI(s), e.g. 10.17605/OSF.IO/WZUBG",
        )

    def handle(self, *args, **options):
        dois = [DOI.get_bare_doi(doi) for doi in options["dois"]]
        invalid = [
            doi
            for doi, bare_doi in zip(options["dois"], dois)
            if not bare_doi or not OSFRegistrationService.get_guid(bare_doi)
        ]
        if invalid:
            raise CommandError(f"Not OSF registration DOIs: {', '.join(invalid)}")

        service = OSFRegistrationService()
        for doi in dois:
            paper = service.import_by_doi(doi)
            if paper:
                self.stdout.write(f"Imported {doi} as paper {paper.id}: {paper.title}")
            else:
                self.stderr.write(f"No public OSF registration imported for {doi}")

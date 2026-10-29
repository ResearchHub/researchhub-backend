"""
Service for importing OSF registrations (DataCite DOIs under 10.17605/OSF.IO)
directly from the OSF API.

OpenAlex can merge an OSF registration into a different work that shares its
title (e.g. a Lifecycle Journal outcomes report into its research plan), so
these DOIs are imported from OSF rather than OpenAlex.
"""

import logging
import re

from paper.ingestion.clients.registrations.osf import OSFRegistrationClient
from paper.ingestion.constants import IngestionSource
from paper.ingestion.mappers.registrations.osf import OSFRegistrationMapper
from paper.ingestion.services.ingestion_service import PaperIngestionService
from paper.models import Paper

logger = logging.getLogger(__name__)

OSF_DOI_PATTERN = re.compile(r"^10\.17605/osf\.io/([a-z0-9]+)$", re.IGNORECASE)


class OSFRegistrationService:
    def __init__(
        self,
        client: OSFRegistrationClient | None = None,
        ingestion_service: PaperIngestionService | None = None,
    ):
        self.client = client or OSFRegistrationClient()
        self.ingestion_service = ingestion_service or PaperIngestionService(
            {IngestionSource.OSF: OSFRegistrationMapper()}
        )

    @staticmethod
    def get_guid(doi: str) -> str | None:
        """Return the OSF GUID for an OSF DOI, or None for any other DOI."""
        match = OSF_DOI_PATTERN.match(doi.strip())
        return match.group(1).lower() if match else None

    def import_by_doi(self, doi: str) -> Paper | None:
        """
        Import the OSF registration identified by a bare DOI.

        Returns:
            The created or updated Paper, or None if the DOI is not an OSF DOI
            or does not belong to a public registration.
        """
        guid = self.get_guid(doi)
        if not guid:
            return None

        record = self.client.fetch_registration(guid)
        if record is None:
            logger.info("No public OSF registration found for DOI %s", doi)
            return None

        record["doi"] = doi
        paper = self.ingestion_service.ingest_single_paper(record, IngestionSource.OSF)
        if paper:
            # Reload so fields set from strings (e.g. dates) have their DB types
            paper.refresh_from_db()
        return paper

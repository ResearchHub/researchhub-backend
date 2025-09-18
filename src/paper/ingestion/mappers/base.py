"""
Base mapper class for transforming source data to domain models.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from hub.models import Hub
from institution.models import Institution
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

logger = logging.getLogger(__name__)


class BaseMapper(ABC):
    """Abstract base class for mapping source data to domain models."""

    @abstractmethod
    def validate(self, record: Dict[str, Any]) -> bool:
        """
        Validate a record has required fields.

        Returns True if valid, False if should be skipped.
        """
        pass

    @abstractmethod
    def map_to_paper(self, record: Dict[str, Any]) -> Paper:
        """
        Map source-specific record to Paper model instance.

        Must be implemented by each mapper.
        Returns Paper instance (not saved to database).
        """
        pass

    @abstractmethod
    def map_to_authors(self, record: Dict[str, Any]) -> List[Author]:
        """
        Map source record to Author model instances.

        Returns list of Author instances (not saved to database).
        Note: Only creates authors with proper identifiers (e.g., ORCID)
        to enable deduplication.
        """
        pass

    @abstractmethod
    def map_to_institutions(self, record: Dict[str, Any]) -> List[Institution]:
        """
        Map source record to Institution model instances.

        Returns list of Institution instances (not saved to database).
        Note: Only creates institutions with proper identifiers (e.g., ROR ID)
        to enable deduplication.
        """
        pass

    @abstractmethod
    def map_to_authorships(
        self, paper: Paper, record: Dict[str, Any]
    ) -> List[Authorship]:
        """
        Map source record to Authorship model instances for a given paper.

        Args:
            paper: The Paper instance to create authorships for
            record: Source record containing author data

        Returns:
            List of Authorship instances (not saved to database).
            These connect authors to the paper with position and institution data.
        """
        pass

    @abstractmethod
    def map_to_hubs(self, paper: Paper, record: Dict[str, Any]) -> List[Hub]:
        """
        Map source record to Hub (tag) model instances for a given paper.

        Args:
            paper: The Paper instance to create tags for
            record: Source record containing tag data
        """
        pass

    def map_batch(
        self, records: List[Dict[str, Any]], validate: bool = True
    ) -> List[Paper]:
        """
        Map a batch of records to Paper model instances.

        Args:
            records: List of source-specific records
            validate: Whether to validate records before mapping

        Returns:
            List of Paper instances (not saved to database)
        """
        mapped_records = []
        for record in records:
            try:
                if validate and not self.validate(record):
                    logger.debug(
                        f"Skipped invalid record: {record.get('id', 'unknown')}"
                    )
                    continue
                mapped = self.map_to_paper(record)
                mapped_records.append(mapped)
            except Exception as e:
                logger.error(f"Error mapping record: {e}")
        return mapped_records

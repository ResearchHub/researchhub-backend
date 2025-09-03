"""
Base mapper class for transforming source data to domain models.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

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
    def map_to_paper(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map source-specific record to Paper model fields.

        Must be implemented by each mapper.
        """
        pass

    def map_batch(
        self, records: List[Dict[str, Any]], validate: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Map a batch of records to Paper model fields.

        Args:
            records: List of source-specific records
            validate: Whether to validate records before mapping

        Returns:
            List of mapped Paper records
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

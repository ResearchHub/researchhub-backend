"""
Factory for creating mapper instances with hub mapper configuration.
"""

from typing import Dict

from hub.mappers.external_category_mapper import ExternalCategoryMapper
from paper.ingestion.constants import IngestionSource
from paper.ingestion.mappers.arxiv_oaipmh import ArXivOAIPMHMapper

from .arxiv import ArXivMapper
from .base import BaseMapper
from .biorxiv import BioRxivMapper
from .chemrxiv import ChemRxivMapper
from .medrxiv import MedRxivMapper
from .openalex import OpenAlexMapper


class MapperFactory:
    """
    Factory for creating mapper instances with their configuration.
    """

    _hub_mapper = ExternalCategoryMapper()

    def create_mappers(self) -> Dict[IngestionSource, BaseMapper]:
        """
        Create all mapper instances.
        """
        return {
            IngestionSource.ARXIV: ArXivMapper(
                hub_mapper=self._hub_mapper,
            ),
            IngestionSource.ARXIV_OAIPMH: ArXivOAIPMHMapper(
                hub_mapper=self._hub_mapper
            ),
            IngestionSource.BIORXIV: BioRxivMapper(
                hub_mapper=self._hub_mapper,
            ),
            IngestionSource.CHEMRXIV: ChemRxivMapper(
                hub_mapper=self._hub_mapper,
            ),
            IngestionSource.MEDRXIV: MedRxivMapper(
                hub_mapper=self._hub_mapper,
            ),
            IngestionSource.OPENALEX: OpenAlexMapper(),
        }

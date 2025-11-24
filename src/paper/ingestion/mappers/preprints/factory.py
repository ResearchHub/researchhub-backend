"""
Factory for creating mapper instances with hub mapper configuration.
"""

from typing import Dict

from hub.mappers.external_category_mapper import ExternalCategoryMapper
from paper.ingestion.constants import IngestionSource

from ..base import BaseMapper
from ..enrichment.openalex import OpenAlexMapper
from .arxiv import ArXivMapper
from .arxiv_oai import ArXivOAIMapper
from .biorxiv import BioRxivMapper
from .chemrxiv import ChemRxivMapper
from .medrxiv import MedRxivMapper


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
            IngestionSource.ARXIV_OAI: ArXivOAIMapper(hub_mapper=self._hub_mapper),
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

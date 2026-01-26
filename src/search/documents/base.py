import logging
import math
from typing import override

from django_opensearch_dsl import Document

logger = logging.getLogger(__name__)


class BaseDocument(Document):
    # Weight multipliers for suggestion phrases in completion suggester
    TITLE_WEIGHT = 10.0
    TITLE_WORDS_WEIGHT = 8.0
    BIGRAM_WEIGHT = 7.0
    DOI_WEIGHT = 6.0
    AUTHOR_WEIGHT = 4.0
    JOURNAL_WEIGHT = 3.0
    HUB_WEIGHT = 2.0
    DEFAULT_WEIGHT = 1.0

    def calculate_phrase_weight(self, hot_score_v2: int, phrase_weight: float) -> int:
        """
        Calculate final weight for a suggestion phrase.
        Applies logarithmic scaling to (hot_score_v2 * phrase_weight) to compress the range
        while incorporating phrase type priority into the log calculation.
        """
        if hot_score_v2 > 0:
            return int(math.log(hot_score_v2 * phrase_weight, 10) * 10)
        return int(phrase_weight)

    @override
    def _get_actions(self, object_list, action):
        """
        Override the base `_get_actions` method to support soft-delete behavior.
        Additionally, any exceptions from the prepare_[field] methods will be
        logged without aborting the indexing process.
        """
        for object_instance in object_list:
            if action == "delete" or self.should_index_object(object_instance):
                # Execute `prepare` methods with graceful error handling to avoid
                # aborting the indexing process:
                try:
                    yield self._prepare_action(object_instance, action)
                except Exception as e:
                    logger.warning(
                        f"Failed to index {self.__class__.__name__} "
                        f"id={object_instance.id}: {e}"
                    )
                    continue
            else:
                # delete soft-deleted objects (`should_index_object` is False)
                yield self._prepare_action(object_instance, "delete")

from celery.utils.log import get_task_logger

from hub.models import Hub
from paper.openalex_util import OPENALEX_SOURCES_TO_JOURNAL_HUBS
from researchhub.celery import QUEUE_PAPER_METADATA, app
from topic.models import Topic, UnifiedDocumentTopics

logger = get_task_logger(__name__)


# Mapping of external source names to preprint hub slugs.
PREPRINT_SOURCES_TO_HUB_SLUGS = {
    "arxiv": "arxiv",
    "arxiv (cornell university)": "arxiv",
    "biorxiv": "biorxiv",
    "biorxiv (cold spring harbor laboratory)": "biorxiv",
    "chemrxiv": "chemrxiv",
    "medrxiv": "medrxiv",
    "medrxiv (cold spring harbor laboratory)": "medrxiv",
}


@app.task(queue=QUEUE_PAPER_METADATA)
def create_paper_related_tags(paper, openalex_topics=None):
    # Process topics
    if openalex_topics is None:
        openalex_topics = []
    sorted_topics = sorted(openalex_topics, key=lambda x: x["score"], reverse=True)
    topic_ids = []
    topic_relevancy = {}

    for index, openalex_topic in enumerate(sorted_topics):
        try:
            topic = Topic.upsert_from_openalex(openalex_topic)
            topic_ids.append(topic.id)
            topic_relevancy[topic.id] = {
                "relevancy_score": openalex_topic["score"],
                "is_primary": index == 0,
            }

            # Add subfield hub
            subfield_hub = Hub.get_from_subfield(topic.subfield)
            paper.unified_document.hubs.add(subfield_hub)
        except Exception:
            logger.exception("Failed to process topic for paper %s", paper.id)

    # Bulk create/update UnifiedDocumentTopics
    UnifiedDocumentTopics.objects.bulk_create(
        [
            UnifiedDocumentTopics(
                unified_document=paper.unified_document,
                topic_id=topic_id,
                relevancy_score=topic_relevancy[topic_id]["relevancy_score"],
                is_primary=topic_relevancy[topic_id]["is_primary"],
            )
            for topic_id in topic_ids
        ],
        ignore_conflicts=True,
    )

    if paper.external_source:
        journal = _get_or_create_journal_hub(paper.external_source)
        paper.unified_document.hubs.add(journal)

    # Add preprint hub for papers from preprint servers
    _add_preprint_hub_if_applicable(paper)


def _get_or_create_journal_hub(external_source: str) -> Hub:
    """
    Get or create a journal hub from the given journal name.
    This function also considers the managed mapping of OpenAlex sources to journal hubs
    in `OPENALEX_SOURCES_TO_JOURNAL_HUBS`.
    """
    journal_hub = None

    if external_source in OPENALEX_SOURCES_TO_JOURNAL_HUBS:
        journal_hub = _get_journal_hub(
            OPENALEX_SOURCES_TO_JOURNAL_HUBS[external_source]
        )

    if journal_hub is None:
        journal_hub = _get_journal_hub(external_source)
        if journal_hub is None:
            journal_hub = Hub.objects.create(
                name=external_source,
                namespace=Hub.Namespace.JOURNAL,
            )

    return journal_hub


def _get_journal_hub(journal: str) -> Hub:
    return Hub.objects.filter(
        name__iexact=journal,
        namespace=Hub.Namespace.JOURNAL,
    ).first()


def _add_preprint_hub_if_applicable(paper) -> None:
    """
    Add the preprint hub to a paper if it comes from a preprint server.

    This function checks if the paper's external_source is a known preprint server
    (arxiv, biorxiv, medrxiv, chemrxiv) and adds the corresponding preprint hub
    to the paper's unified document.

    Args:
        paper: The Paper instance to add the preprint hub to
    """
    if not paper.external_source:
        return

    external_source_lower = paper.external_source.lower()
    hub_slug = PREPRINT_SOURCES_TO_HUB_SLUGS.get(external_source_lower)

    if hub_slug:
        preprint_hub = Hub.objects.filter(
            slug=hub_slug,
            namespace=Hub.Namespace.JOURNAL,
        ).first()

        if preprint_hub:
            paper.unified_document.hubs.add(preprint_hub)

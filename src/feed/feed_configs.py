"""
Feed configurations for different entity types.

This module contains the feed configurations for all entity types that participate
in the feed system. Each configuration defines how that entity type should behave
when creating, updating, or deleting feed entries.
"""

from django.contrib.contenttypes.models import ContentType

from feed.feed_manager import (
    FeedConfig,
    get_hub_ids_from_unified_document,
    get_unified_document_default,
    get_user_created_by,
    get_user_uploaded_by,
    register_feed_entity,
)
from feed.models import FeedEntry


def get_comment_unified_document(comment):
    """Get unified document from a comment through its thread."""
    if hasattr(comment, "thread") and comment.thread:
        return getattr(comment.thread, "unified_document", None)
    return getattr(comment, "unified_document", None)


def get_comment_related_entities(comment):
    """Get entities that need metric updates when a comment changes."""
    entities = []

    # Update metrics for the parent document (paper/post)
    unified_document = get_comment_unified_document(comment)
    if unified_document:
        document = unified_document.get_document()
        if document:
            entities.append(document)

    # Update metrics for parent comment if it exists
    if hasattr(comment, "parent") and comment.parent:
        entities.append(comment.parent)

    return entities


def get_paper_action_date(paper):
    """Get the appropriate action date for a paper."""
    return getattr(paper, "paper_publish_date", paper.created_date)


def register_all_feed_entities():
    """Register all entity types with the feed manager."""

    # ResearchhubPost configuration
    from researchhub_document.models import ResearchhubPost

    register_feed_entity(
        FeedConfig(
            model_class=ResearchhubPost,
            feed_actions=[FeedEntry.PUBLISH],
            get_unified_document=get_unified_document_default,
            get_hub_ids=get_hub_ids_from_unified_document,
            get_user=get_user_created_by,
            create_on_save=True,
            delete_on_remove=True,
            update_related_metrics=False,
        )
    )

    # Comment configuration
    from researchhub_comment.related_models.rh_comment_model import RhCommentModel

    register_feed_entity(
        FeedConfig(
            model_class=RhCommentModel,
            feed_actions=[FeedEntry.PUBLISH],
            get_unified_document=get_comment_unified_document,
            get_hub_ids=get_hub_ids_from_unified_document,
            get_user=get_user_created_by,
            create_on_save=True,
            delete_on_remove=True,
            update_related_metrics=True,
            get_related_entities=get_comment_related_entities,
        )
    )

    # Paper configuration
    from paper.models import Paper

    register_feed_entity(
        FeedConfig(
            model_class=Paper,
            feed_actions=[FeedEntry.PUBLISH],
            get_unified_document=get_unified_document_default,
            get_hub_ids=get_hub_ids_from_unified_document,
            get_user=get_user_uploaded_by,
            get_action_date=get_paper_action_date,
            create_on_save=True,
            delete_on_remove=True,
            update_related_metrics=False,
        )
    )

    # Bounty configuration (if bounty model exists)
    try:
        from reputation.related_models.bounty import Bounty

        register_feed_entity(
            FeedConfig(
                model_class=Bounty,
                feed_actions=[FeedEntry.OPEN],  # Bounties use OPEN action
                get_unified_document=get_unified_document_default,
                get_hub_ids=get_hub_ids_from_unified_document,
                get_user=get_user_created_by,
                create_on_save=True,
                delete_on_remove=True,
                update_related_metrics=False,
            )
        )
    except ImportError:
        # Bounty model might not exist or be in a different location
        pass

    # Review configuration (if review model exists)
    try:
        from review.models import Review

        register_feed_entity(
            FeedConfig(
                model_class=Review,
                feed_actions=[FeedEntry.PUBLISH],
                get_unified_document=get_unified_document_default,
                get_hub_ids=get_hub_ids_from_unified_document,
                get_user=get_user_created_by,
                create_on_save=True,
                delete_on_remove=True,
                update_related_metrics=False,
            )
        )
    except ImportError:
        # Review model might not exist or be in a different location
        pass


def setup_m2m_signals():
    """Set up many-to-many relationship signals for hub changes."""
    from django.db.models.signals import m2m_changed
    from django.dispatch import receiver

    from feed.feed_manager import feed_manager
    from hub.models import Hub
    from researchhub_document.related_models.researchhub_unified_document_model import (
        ResearchhubUnifiedDocument,
    )

    @receiver(
        m2m_changed,
        sender=ResearchhubUnifiedDocument.hubs.through,
        dispatch_uid="generic_unified_doc_hubs_changed",
    )
    def handle_document_hubs_changed(sender, instance, action, pk_set, **kwargs):
        """Handle hub changes for unified documents."""
        try:
            if isinstance(instance, ResearchhubUnifiedDocument):
                if (
                    instance.document_type == "PAPER"
                    or instance.document_type == "DISCUSSION"
                ):
                    document = instance.get_document()
                    if document and feed_manager.is_registered(type(document)):
                        feed_manager.handle_hubs_changed(document, action, pk_set)
            elif isinstance(instance, Hub):
                # Handle when documents are added/removed from a hub
                for document_id in pk_set:
                    try:
                        unified_document = instance.related_documents.get(
                            id=document_id
                        )
                        document = unified_document.get_document()
                        if document and feed_manager.is_registered(type(document)):
                            if action == "post_add":
                                feed_manager.handle_hubs_changed(
                                    document, action, {instance.id}
                                )
                            elif action == "post_remove":
                                feed_manager.handle_hubs_changed(
                                    document, action, {instance.id}
                                )
                    except Exception as e:
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.error(
                            f"Failed to handle hub change for document {document_id}: {e}"
                        )
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to handle document hub changes: {e}")

# Analytics related mapping functions. Needed for sending structured data to analytics providers such as Segment.io and Amazon Personalize.

import time
from datetime import datetime

import segment.analytics as analytics

from discussion.reaction_models import Vote
from paper.utils import format_raw_authors
from researchhub_comment.related_models.rh_comment_model import RhCommentModel


def log_analytics_event(action):
    if action.content_type.model == "vote" and action.item.vote_type == Vote.UPVOTE:
        properties = build_vote_event(action)
        analytics.track(properties["user_id"], properties["event_type"], properties)
    elif action.content_type.model == "bounty":
        properties = build_bounty_event(action)
        analytics.track(properties["user_id"], properties["event_type"], properties)
    elif action.content_type.model == "rhcommentmodel":
        properties = build_comment_event(action)
        analytics.track(properties["user_id"], properties["event_type"], properties)


def build_bounty_event(action):
    bounty = action.item
    is_contribution = (
        str(bounty.created_by_id) == str(action.user_id) and bounty.parent is not None
    )

    record = {}
    record["item_id"] = "bounty_" + str(bounty.id)
    record["internal_item_id"] = str(bounty.id)
    record["user_id"] = str(action.user_id)
    record["amount_offered"] = bounty.amount
    record["event_type"] = "bounty_contribution" if is_contribution else "bounty_create"

    if isinstance(bounty.item, RhCommentModel):
        record["related_comment_id"] = "comment_" + str(bounty.id)

    if bounty.unified_document:
        doc_props = build_doc_props_for_interaction(bounty.unified_document)
        record = {**record, **doc_props}

    return record


def build_vote_event(action):
    vote = action.item

    record = {}
    if vote.vote_type == Vote.UPVOTE:
        record["event_type"] = "upvote"
    elif vote.vote_type == Vote.DOWNVOTE:
        record["event_type"] = "downvote"

    record["item_id"] = "vote_" + str(vote.id)
    record["internal_item_id"] = str(vote.id)
    record["user_id"] = str(action.user_id)

    if vote.unified_document:
        doc_props = build_doc_props_for_interaction(vote.unified_document)
        record = {**record, **doc_props}

    return record


def build_comment_event(action):
    comment = action.item

    record = {}
    record["item_id"] = "comment_" + str(comment.id)
    record["internal_item_id"] = str(comment.id)
    record["user_id"] = str(action.user_id)
    record["event_type"] = "comment_create"

    if comment.unified_document:
        doc_props = build_doc_props_for_interaction(comment.unified_document)
        record = {**record, **doc_props}

    return record


def parse_year_from_date(date_string):
    try:
        date_object = datetime.strptime(str(date_string), "%Y-%m-%d")
        year = date_object.year
        return year
    except ValueError:
        print("Failed to parse date", date_string)
        return None


def std_date(date_string, format="%Y-%m-%d"):
    try:
        date_object = datetime.strptime(str(date_string), format)
        return date_object.strftime(format)
    except ValueError:
        print("Failed to parse date", date_string)
        return None


def build_hub_props_from_unified_doc(unified_doc):
    from researchhub_document.related_models.researchhub_unified_document_model import (
        UnifiedDocumentConcepts,
    )

    props = {}

    # Add hubs
    hubs = unified_doc.hubs.all()
    relevant_hub_slugs = [f"{hub.slug}" for hub in hubs]
    props["hub_slugs"] = ";".join(relevant_hub_slugs)
    relevant_hubs = [f"{hub.name}" for hub in hubs]
    props["hubs"] = ";".join(relevant_hubs)

    primary_concept = (
        UnifiedDocumentConcepts.objects.filter(unified_document=unified_doc)
        .order_by("-relevancy_score")
        .first()
    )
    if primary_concept:
        props["primary_hub"] = primary_concept.concept.hub.name

    return props


def build_hub_props_for_interaction(action):
    hubs = action.hubs.all()
    hubs_list = hubs.values_list("name", flat=True)
    hub_slug_list = hubs.values_list("slug", flat=True)

    return {
        "hubs": ",".join(hubs_list),
        "hub_slugs": ",".join(hub_slug_list),
    }


def build_doc_props_for_interaction(unified_doc):
    props = {}
    specific_doc = unified_doc.get_document()
    document_type = unified_doc.get_client_doc_type()

    props["unified_document_id"] = str(unified_doc.id)
    props["related_item_id"] = document_type + "_" + str(specific_doc.id)
    props["related_item_type"] = document_type
    props["title"] = specific_doc.title

    hub_props = build_hub_props_for_interaction(unified_doc)
    props = {**props, **hub_props}

    return props


def build_doc_props_for_item(unified_doc):
    item_type = unified_doc.get_client_doc_type()
    specific_doc = unified_doc.get_document()  # paper, post, ...
    mapped = {
        "unified_document_id": str(unified_doc.id),
        "title": specific_doc.title,
        "slug": specific_doc.slug,
    }

    if item_type == "paper":
        paper = specific_doc
        mapped["pdf_license"] = paper.pdf_license
        mapped["oa_status"] = paper.oa_status
        mapped["authors"] = format_raw_authors(paper.raw_authors)
        mapped["journal"] = paper.external_source
        mapped["twitter_score"] = paper.twitter_score

        # Parse the authors' list to include only names
        authors_list = format_raw_authors(paper.raw_authors)
        names_only = [
            f"{author['first_name']} {author['last_name']}"
            for author in authors_list
            if author["first_name"] and author["last_name"]
        ]
        mapped["authors"] = ", ".join(names_only)

        if paper.paper_publish_date:
            mapped["publication_year"] = parse_year_from_date(paper.paper_publish_date)
            mapped["publication_timestamp"] = int(
                time.mktime(paper.paper_publish_date.timetuple())
            )

    else:
        authors_list = [
            f"{author.first_name} {author.last_name}"
            for author in unified_doc.authors
            if author.first_name and author.last_name
        ]
        mapped["authors"] = ", ".join(authors_list)

    # Add hub props
    hub_props = build_hub_props_from_unified_doc(unified_doc)
    mapped = {**mapped, **hub_props}

    return mapped

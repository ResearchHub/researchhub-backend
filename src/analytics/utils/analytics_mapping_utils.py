# Analytics related mapping functions. Needed for sending structured data to analytics providers such as Segment.io and Amazon Personalize.

import time
from datetime import datetime

from discussion.reaction_models import Vote
from paper.related_models.paper_model import Paper
from paper.utils import format_raw_authors


def build_hub_str(hub):
    return "NAME:" + str(hub.name) + ";ID:" + str(hub.id)


def build_bounty_event(action):
    bounty = action.item
    is_contribution = (
        str(bounty.created_by_id) == str(action.user_id) and bounty.parent is not None
    )

    record = {}
    record["ITEM_ID"] = bounty.get_analytics_id()
    record["TIMESTAMP"] = int(time.mktime(bounty.created_date.timetuple()))
    record["USER_ID"] = str(action.user_id)
    record["EVENT_VALUE"] = bounty.amount
    record["EVENT_TYPE"] = "bounty_contribution" if is_contribution else "bounty_create"
    record["internal_id"] = str(bounty.id)

    if bounty.unified_document:
        doc_props = build_doc_props_for_interaction(bounty.unified_document)
        record = {**record, **doc_props}

    return record


def build_vote_event(action):
    vote = action.item

    record = {}
    if vote.vote_type == Vote.UPVOTE:
        record["EVENT_TYPE"] = "upvote"
    elif vote.vote_type == Vote.DOWNVOTE:
        record["EVENT_TYPE"] = "downvote"

    try:
        record["ITEM_ID"] = vote.item.get_analytics_id()
    except Exception as e:
        if vote.paper:
            record["ITEM_ID"] = vote.paper.get_analytics_id()
        else:
            print("Failed to get ITEM_ID", vote)
            raise Exception("Failed to get ITEM_ID:", e, vote)

    record["TIMESTAMP"] = int(time.mktime(vote.created_date.timetuple()))
    record["USER_ID"] = str(action.user_id)
    record["internal_id"] = str(vote.id)

    try:
        doc_props = build_doc_props_for_interaction(vote.unified_document)
        record = {**record, **doc_props}
    except Exception as e:
        record["primary_hub"] = ""
        record["unified_document_id"] = ""

    return record


def build_comment_event(action):
    comment = action.item

    record = {}
    record["ITEM_ID"] = comment.get_analytics_id()
    record["TIMESTAMP"] = int(time.mktime(comment.created_date.timetuple()))
    record["USER_ID"] = str(action.user_id)
    record["EVENT_TYPE"] = "comment_create"
    record["internal_id"] = str(comment.id)

    if comment.unified_document:
        doc_props = build_doc_props_for_interaction(comment.unified_document)
        record = {**record, **doc_props}

    return record


def build_rsc_spend_event(action):
    from purchase.related_models.purchase_model import Purchase

    purchase = action.item

    record = {}
    record["ITEM_ID"] = purchase.item.get_analytics_id()
    record["TIMESTAMP"] = int(time.mktime(purchase.created_date.timetuple()))
    record["USER_ID"] = str(action.user_id)
    record["EVENT_VALUE"] = purchase.amount
    record["internal_id"] = str(purchase.id)

    # As far as Amazon Personalize events go, we are only interested in select rsc spend events and not all
    if purchase.purchase_type == Purchase.BOOST:
        record["EVENT_TYPE"] = "support_item_with_rsc"
    elif purchase.purchase_type == Purchase.FUNDRAISE_CONTRIBUTION:
        record["EVENT_TYPE"] = "support_fundraise_with_rsc"

    try:
        if purchase.item.unified_document:
            doc_props = build_doc_props_for_interaction(purchase.item.unified_document)
            record = {**record, **doc_props}
    except Exception as e:
        print("Failed to get unified doc:", e)

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
    hubs = unified_doc.hubs.all()

    concepts = UnifiedDocumentConcepts.objects.filter(
        unified_document=unified_doc
    ).order_by("-relevancy_score")
    if len(concepts) > 0:
        props["hubs"] = "|".join(
            [build_hub_str(ranked_concept.concept.hub) for ranked_concept in concepts]
        )
    elif len(hubs) > 0:
        props["hubs"] = "|".join([build_hub_str(hub) for hub in hubs])

    return props


def build_hub_props_for_interaction(unified_doc):
    from researchhub_document.related_models.researchhub_unified_document_model import (
        UnifiedDocumentConcepts,
    )

    props = {}
    if unified_doc:
        hubs = unified_doc.hubs.all()

        concepts = UnifiedDocumentConcepts.objects.filter(
            unified_document=unified_doc
        ).order_by("-relevancy_score")

        if len(concepts) > 0:
            props["hubs"] = "|".join(
                [
                    build_hub_str(ranked_concept.concept.hub)
                    for ranked_concept in concepts
                ]
            )
        elif len(hubs) > 0:
            props["hubs"] = "|".join([build_hub_str(hub) for hub in hubs])

    return props


def build_doc_props_for_interaction(unified_doc):
    props = {}
    props["unified_document_id"] = str(unified_doc.id)

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
        mapped["authors"] = ""
        mapped["journal"] = paper.external_source
        mapped["twitter_score"] = paper.twitter_score

        try:
            # Parse the authors' list to include only names
            authors_list = format_raw_authors(paper.raw_authors)
            names_only = [
                f"{author['first_name']} {author['last_name']}"
                for author in authors_list
                if author["first_name"] and author["last_name"]
            ]
            mapped["authors"] = ", ".join(names_only)
        except Exception as e:
            print("Failed to parse authors:", e)
            print("paper:", paper.id)

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

    try:
        mapped["discussion_count"] = specific_doc.discussion_count
        mapped["hot_score"] = unified_doc.hot_score
    except Exception as e:
        pass

    # Add hub props
    hub_props = build_hub_props_from_unified_doc(unified_doc)
    mapped = {**mapped, **hub_props}

    return mapped

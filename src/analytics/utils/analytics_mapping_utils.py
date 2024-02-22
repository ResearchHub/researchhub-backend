# Analytics related mapping functions. Needed for sending structured data to analytics providers such as Segment.io and Amazon Personalize.

import time
from datetime import datetime

from discussion.reaction_models import Vote
from paper.related_models.paper_model import Paper
from paper.utils import format_raw_authors
from reputation.related_models.bounty import Bounty

# Event values correspond to the user's potential interest in the item's topics (hubs)
# on a scale of 1-10. The higher the value, the more interest the user has in the item.
PAGE_VIEW_EVENT_VALUE = 1  # This will be used on the client side
VOTE_EVENT_VALUE = 2
RSC_SUPPORT_EVENT_VALUE = 5
BOUNTY_EVENT_VALUE = 8
COMMENT_EVENT_VALUE = 8
CLAIMED_PAPER_EVENT_VALUE = 10


def build_bounty_event(action):
    bounty = action.item
    is_contribution = (
        str(bounty.created_by_id) == str(action.user_id) and bounty.parent is not None
    )

    record = {}
    record["ITEM_ID"] = bounty.get_analytics_id()
    record["TIMESTAMP"] = int(time.mktime(bounty.created_date.timetuple()))
    record["USER_ID"] = str(action.user_id)
    record["EVENT_VALUE"] = BOUNTY_EVENT_VALUE
    record["EVENT_TYPE"] = "bounty_contribution" if is_contribution else "bounty_create"
    record["internal_id"] = str(bounty.id)

    if bounty.unified_document:
        doc_props = build_doc_props_for_interaction(bounty.unified_document)
        record = {**record, **doc_props}

    return record


def build_vote_event(action):
    vote = action.item

    record = {}
    record["EVENT_VALUE"] = VOTE_EVENT_VALUE
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


def build_claimed_paper_event(author_claim_case):
    claimed_paper = author_claim_case.target_paper

    record = {}
    record["EVENT_VALUE"] = CLAIMED_PAPER_EVENT_VALUE
    record["ITEM_ID"] = claimed_paper.get_analytics_id()
    record["TIMESTAMP"] = int(time.mktime(claimed_paper.created_date.timetuple()))
    record["USER_ID"] = str(author_claim_case.requestor_id)
    record["EVENT_TYPE"] = "claimed_paper"
    record["internal_id"] = str(claimed_paper.id)

    if claimed_paper.unified_document:
        doc_props = build_doc_props_for_interaction(claimed_paper.unified_document)
        record = {**record, **doc_props}

    return record


def build_comment_event(action):
    comment = action.item

    record = {}
    record["EVENT_VALUE"] = COMMENT_EVENT_VALUE
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
    record["EVENT_VALUE"] = RSC_SUPPORT_EVENT_VALUE
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

    ranked_concepts = UnifiedDocumentConcepts.objects.filter(
        unified_document=unified_doc
    ).order_by("-relevancy_score")

    hub_ids = []
    hub_metadata = []
    if len(ranked_concepts) > 0:
        for ranked_concept in ranked_concepts:
            try:
                if ranked_concept.concept and hasattr(ranked_concept.concept, "hub"):
                    hub_ids.append(str(ranked_concept.concept.hub.id))
                    hub_metadata.append(
                        "hub_id: "
                        + str(ranked_concept.concept.hub.id)
                        + " -- hub_name: "
                        + str(ranked_concept.concept.hub.name)
                    )
            except Exception as e:
                pass

    elif len(hubs) > 0:
        for hub in hubs:
            try:
                hub_ids.append(str(hub.id))
                hub_metadata.append(
                    "hub_id: " + str(hub.id) + " -- hub_name: " + str(hub.name)
                )

            except Exception as e:
                pass

    props["hub_ids"] = ";".join(hub_ids)
    props["hub_metadata"] = ";".join(hub_metadata)

    return props


def build_doc_props_for_interaction(unified_doc):
    props = {}
    props["unified_document_id"] = str(unified_doc.id)

    hub_props = build_hub_props_from_unified_doc(unified_doc)
    props = {**props, **hub_props}

    return props


def get_open_bounty_count(unified_document):
    return len(
        Bounty.objects.filter(unified_document=unified_document.id, status=Bounty.OPEN)
    )


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
        mapped["body"] = paper.abstract

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

        if paper.open_alex_raw_json:
            open_alex_data = paper.open_alex_raw_json
            try:
                mapped["keywords"] = ",".join(
                    [
                        keyword_obj["keyword"]
                        for keyword_obj in open_alex_data["keywords"]
                    ]
                )
            except Exception as e:
                pass

            try:
                mapped["cited_by_count"] = open_alex_data["cited_by_count"]
            except Exception as e:
                pass

            try:
                mapped["citation_percentile_performance"] = open_alex_data[
                    "cited_by_percentile_year"
                ]["max"]
            except Exception as e:
                pass

            try:
                years_cited = open_alex_data["counts_by_year"]
                # Let's use 2 years for now to determine if a paper is trending citation wise
                mapped["is_trending_citations"] = False
                if len(years_cited) >= 2:
                    one_year_ago = years_cited[0]["cited_by_count"]
                    two_years_ago = years_cited[1]["cited_by_count"]

                    # 25% growth over the previous year is sufficient to be considered trending
                    if (
                        one_year_ago > two_years_ago
                        and one_year_ago >= two_years_ago * 1.25
                    ):
                        mapped["is_trending_citations"] = True
            except Exception as e:
                pass

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

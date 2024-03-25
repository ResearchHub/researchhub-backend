import time
from datetime import datetime

import dateutil.relativedelta

from analytics.utils.analytics_mapping_utils import (
    build_bounty_event,
    build_claimed_paper_event,
    build_comment_event,
    build_doc_props_for_item,
    build_paper_submission_event,
    build_post_created_event,
    build_rsc_spend_event,
    build_vote_event,
    get_open_bounty_count,
)
from discussion.reaction_models import Vote
from purchase.related_models.purchase_model import Purchase
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW


def map_action_data(actions, on_error):
    data = []
    for action in actions:
        try:
            if action.item is None:
                raise Exception(f"Action {action.id}'s item is None")

            if action.content_type.model == "bounty":
                event = build_bounty_event(action)
                data.append(event)
            elif action.content_type.model == "vote":
                if action.item.vote_type == Vote.DOWNVOTE:
                    on_error(
                        id=str(action.id),
                        msg="Unsupported action type (downvote). Skipping.",
                    )
                    # Skip downvotes since they are not beneficial for machine learning models
                    continue

                event = build_vote_event(action)
                data.append(event)
            elif action.content_type.model == "rhcommentmodel":
                event = build_comment_event(action)
                data.append(event)
            elif action.content_type.model == "purchase":
                if (
                    action.item.purchase_type == Purchase.BOOST
                    or action.item.purchase_type == Purchase.FUNDRAISE_CONTRIBUTION
                ):
                    event = build_rsc_spend_event(action)

                data.append(event)
            elif action.content_type.model == "paper":
                event = build_paper_submission_event(action)
                data.append(event)
            elif action.content_type.model == "researchhubpost":
                event = build_post_created_event(action)
                data.append(event)
            else:
                on_error(id=str(action.id), msg="Unsupported action type. Skipping.")
        except Exception as e:
            on_error(id=str(action.id), msg=str(e))

    return data


def map_claim_data(claim_cases, on_error):
    data = []
    for claim in claim_cases:
        try:
            event = build_claimed_paper_event(claim)
            data.append(event)
        except Exception as e:
            print("Failed to export claim: " + str(claim.id), e)

    return data


def map_paper_data(papers, on_error):
    data = []
    for paper in papers:
        try:
            open_alex_data = paper.open_alex_raw_json

            citation_percentile = 0
            try:
                citation_percentile = open_alex_data["cited_by_percentile_year"]["min"]
            except Exception as e:
                pass

            cited_by_count = 0
            try:
                cited_by_count = open_alex_data["cited_by_count"] or 0
            except Exception as e:
                pass

            paper_published_less_than_three_months_ago = False
            three_months_ago = datetime.now() - dateutil.relativedelta.relativedelta(
                months=3
            )
            try:
                paper_published_less_than_three_months_ago = (
                    paper.paper_publish_date.date() > three_months_ago
                )
            except Exception as e:
                pass

            paper_has_at_least_1_citation = cited_by_count >= 1
            paper_has_activity = paper.discussion_count > 0 or paper.twitter_score > 0
            should_include = False

            if paper_has_activity:
                should_include = True
            elif (
                paper_has_at_least_1_citation
                and paper_published_less_than_three_months_ago
            ):
                should_include = True
            elif paper.is_highly_cited:
                should_include = True

            if should_include is False:
                on_error(
                    id=str(paper.id),
                    msg=f"Skipping paper. paper_has_activity: {str(paper_has_activity)}, paper_has_at_least_1_citation: {str(paper_has_at_least_1_citation)}, paper_published_less_than_three_months_ago: {str(paper_published_less_than_three_months_ago)}, paper_is_highly_cited: {str(paper_is_highly_cited)}",
                )
                continue

            record = {}
            doc = paper.unified_document
            doc_props = build_doc_props_for_item(doc)
            record = {**doc_props}
            record["ITEM_ID"] = paper.get_analytics_id()
            record["item_type"] = paper.get_analytics_type()
            record["internal_item_id"] = str(paper.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(doc.created_date.timetuple())
            )
            record["updated_timestamp"] = int(time.mktime(doc.updated_date.timetuple()))
            record["open_bounty_count"] = get_open_bounty_count(doc)
            record["is_highly_cited"] = paper.is_highly_cited
            record["citation_percentile_performance"] = citation_percentile
            record["cited_by_count"] = cited_by_count

            if paper.created_by:
                record["created_by_user_id"] = str(paper.created_by.id)

            try:
                years_cited = open_alex_data["counts_by_year"]
                # Let's use 2 years for now to determine if a paper is trending citation wise
                record["is_trending_citations"] = False
                if len(years_cited) >= 2:
                    one_year_ago = years_cited[0]["cited_by_count"]
                    two_years_ago = years_cited[1]["cited_by_count"]

                    # 25% growth over the previous year is sufficient to be considered trending
                    if (
                        one_year_ago > two_years_ago
                        and one_year_ago >= two_years_ago * 1.25
                    ):
                        record["is_trending_citations"] = True
            except Exception as e:
                pass

            try:
                record["keywords"] = ",".join(
                    [
                        keyword_obj["keyword"]
                        for keyword_obj in open_alex_data["keywords"]
                    ]
                )
            except Exception as e:
                pass

            data.append(record)
        except Exception as e:
            on_error(id=str(paper.id), msg=str(e))

    return data


def map_post_data(docs, on_error):
    data = []
    for doc in docs:
        try:
            post = doc.get_document()

            record = {}
            doc_props = build_doc_props_for_item(doc)
            record = {**doc_props}
            record["ITEM_ID"] = post.get_analytics_id()
            record["item_type"] = post.get_analytics_type()
            record["internal_item_id"] = str(post.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(doc.created_date.timetuple())
            )
            record["item_type"] = doc.get_client_doc_type()
            record["updated_timestamp"] = int(time.mktime(doc.updated_date.timetuple()))
            record["open_bounty_count"] = get_open_bounty_count(doc)
            record["body"] = post.renderable_text

            if post.created_by:
                record["created_by_user_id"] = str(post.created_by.id)

            data.append(record)
        except Exception as e:
            on_error(id=str(doc.id), msg=str(e))

    return data


def map_comment_data(comments, on_error):
    data = []

    # Comments, Peer Reviews, ..
    for comment in comments:
        try:
            record = {}
            if comment.unified_document:
                doc_props = build_doc_props_for_item(comment.unified_document)
                record = {**doc_props}
                record["related_unified_document_id"] = comment.unified_document.id
                specific_doc = comment.unified_document.get_document()
                record["related_slug"] = specific_doc.slug

            record["ITEM_ID"] = comment.get_analytics_id()
            record["item_type"] = comment.get_analytics_type()
            record["internal_item_id"] = str(comment.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(comment.created_date.timetuple())
            )
            record["updated_timestamp"] = int(
                time.mktime(comment.updated_date.timetuple())
            )
            record["created_by_user_id"] = str(comment.created_by.id)
            record["author"] = str(comment.created_by.full_name())
            record["discussion_count"] = comment.get_total_children_count()

            # Add bounty
            bounties = comment.bounties.filter(status="OPEN")
            record["open_bounty_count"] = len(bounties)
            record["authors"] = str(comment.created_by.full_name())

            # Peer review metadata
            try:
                if comment.comment_type == PEER_REVIEW:
                    record["peer_review_score"] = comment.reviews.first().score
            except Exception as e:
                pass

            try:
                record["body"] = comment.plain_text
            except Exception as e:
                pass

            data.append(record)
        except Exception as e:
            on_error(id=str(comment.id), msg=str(e))

    return data


def map_bounty_data(bounties, on_error):
    data = []

    for bounty in bounties:
        try:
            record = {}
            if bounty.unified_document:
                doc_props = build_doc_props_for_item(bounty.unified_document)
                record = {**doc_props}
                record["related_unified_document_id"] = bounty.unified_document.id
                specific_doc = bounty.unified_document.get_document()
                record["related_slug"] = specific_doc.slug

            record["ITEM_ID"] = bounty.get_analytics_id()
            record["item_type"] = bounty.get_analytics_type()
            record["bounty_type"] = bounty.bounty_type
            record["internal_item_id"] = str(bounty.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(bounty.created_date.timetuple())
            )

            if bounty.parent:
                record["bounty_parent_id"] = bounty.parent.get_analytics_id()

            record["updated_timestamp"] = int(
                time.mktime(bounty.updated_date.timetuple())
            )
            record["bounty_expiration_timestamp"] = int(
                time.mktime(bounty.expiration_date.timetuple())
            )

            num_days_to_expiry = bounty.get_num_days_to_expiration()
            record["bounty_is_expiring_soon"] = (
                num_days_to_expiry <= 7 and bounty.get_num_days_to_expiration() >= 0
            )
            record["bounty_status"] = bounty.status
            record["bounty_has_solution"] = bounty.solutions.exists()
            record["created_by_user_id"] = str(bounty.created_by.id)
            record["authors"] = str(bounty.created_by.full_name())

            try:
                record["discussion_count"] = bounty.item.get_total_children_count()
            except Exception as e:
                pass

            try:
                record["body"] = bounty.item.plain_text
            except Exception as e:
                pass

            data.append(record)
        except Exception as e:
            on_error(id=str(bounty.id), msg=str(e))

    return data


def map_user_data(queryset, on_error):
    data = []
    for user in queryset:
        try:
            record = {}
            interests = []
            expertise = []

            try:
                interests = user.author_profile.get_interest_hubs()
            except Exception as e:
                pass

            try:
                expertise = user.author_profile.get_expertise_hubs()
            except Exception as e:
                pass

            record["USER_ID"] = str(user.id)

            interest_hub_ids = []
            expertise_hub_ids = []
            for hub in interests:
                try:
                    interest_hub_ids.append(str(hub.id))

                except Exception as e:
                    pass

            for hub in expertise:
                try:
                    expertise_hub_ids.append(str(hub.id))

                except Exception as e:
                    pass

            record["user_interest_hub_ids"] = ";".join(interest_hub_ids)
            record["user_expertise_hub_ids"] = ";".join(expertise_hub_ids)

            data.append(record)

        except Exception as e:
            on_error(id=str(user.id), msg=str(e))

    return data

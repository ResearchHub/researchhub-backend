import time

from analytics.utils.analytics_mapping_utils import (
    build_bounty_event,
    build_claimed_paper_event,
    build_comment_event,
    build_doc_props_for_item,
    build_hub_str,
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
            if action.content_type.model == "bounty":
                event = build_bounty_event(action)
                data.append(event)
            elif action.content_type.model == "vote":
                if action.item.vote_type == Vote.DOWNVOTE:
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


def map_paper_data(docs, on_error):
    from paper.related_models.paper_model import Paper

    data = []
    for doc in docs:
        try:
            paper = doc.get_document()
            # The following clause aims to prevent papers with missing criticial or interesting data (e.g. comments)
            # from being recommneded by Amazon personalize
            completeness = paper.get_paper_completeness()
            if completeness == Paper.PARTIAL:
                if paper.discussion_count == 0:
                    print(
                        "skipping partially completed paper: ",
                        paper.title,
                        paper.id,
                    )
                    continue
            elif completeness == Paper.INCOMPLETE:
                print("skipping incomplete paper: ", paper.title, paper.id)
                continue

            record = {}
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

            if paper.created_by:
                record["created_by_user_id"] = str(paper.created_by.id)

            data.append(record)
        except Exception as e:
            on_error(id=str(doc.id), msg=str(e))

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
            interests = user.author_profile.get_interest_hubs()
            expertise = user.author_profile.get_expertise_hubs()

            record["USER_ID"] = str(user.id)
            record["interest_hubs"] = "|".join(
                [build_hub_str(hub) for hub in interests]
            )
            record["expertise_hubs"] = "|".join(
                [build_hub_str(hub) for hub in expertise]
            )
            data.append(record)

        except Exception as e:
            on_error(id=str(user.id), msg=str(e))

    return data

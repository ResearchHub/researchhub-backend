import time

from analytics.utils.analytics_mapping_utils import (
    build_doc_props_for_item,
    get_open_bounty_count,
)
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW


def map_paper_data(docs):
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
            print("Failed to export doc: " + str(doc.id), e)

    return data


def map_post_data(docs):
    data = []
    for doc in docs:
        try:
            post = doc.get_document()

            record = {}
            doc_props = build_doc_props_for_item(doc)
            record = {**doc_props}
            record["ITEM_ID"] = post.get_analytics_id()
            record["internal_item_id"] = str(post.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(doc.created_date.timetuple())
            )
            record["item_type"] = doc.get_client_doc_type()
            record["updated_timestamp"] = int(time.mktime(doc.updated_date.timetuple()))
            record["open_bounty_count"] = get_open_bounty_count(doc)

            if post.created_by:
                record["created_by_user_id"] = str(post.created_by.id)

            data.append(record)
        except Exception as e:
            print("Failed to export doc: " + str(doc.id), e)

    return data


def map_comment_data(comments):
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
            record["item_type"] = comment.comment_type
            record["internal_item_id"] = str(comment.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(comment.created_date.timetuple())
            )
            record["updated_timestamp"] = int(
                time.mktime(comment.updated_date.timetuple())
            )
            record["created_by_user_id"] = str(comment.created_by.id)
            record["author"] = str(comment.created_by.full_name())

            # Add bounty
            bounties = comment.bounties.filter(status="OPEN")
            record["open_bounty_count"] = len(bounties)

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

            print(record)

            data.append(record)
        except Exception as e:
            print("Failed to export comment:" + str(comment.id), e)

    return data


def map_bounty_data(comments):
    data = []

    # Comments, Peer Reviews, ..
    for comment in comments:
        try:
            record = {}
            if comment.unified_document:
                doc_props = build_doc_props_for_item(comment.unified_document)
                record = {**doc_props}

            record["ITEM_ID"] = comment.get_analytics_id()
            record["item_type"] = comment.comment_type
            record["internal_item_id"] = str(comment.id)
            record["CREATION_TIMESTAMP"] = int(
                time.mktime(comment.created_date.timetuple())
            )
            record["created_by_user_id"] = str(comment.created_by.id)
            record

            bounties = comment.bounties.filter(status="OPEN").order_by("-amount")
            if bounties.exists():
                bounty = bounties.first()
                record["bounty_amount"] = bounty.amount
                record["bounty_id"] = bounty.get_analytics_id()
                record["bounty_type"] = bounty.get_analytics_type()
                record["bounty_expiration_timestamp"] = int(
                    time.mktime(bounty.created_date.timetuple())
                )

            data.append(record)
        except Exception as e:
            print("Failed to export comment:" + str(comment.id), e)

    return data

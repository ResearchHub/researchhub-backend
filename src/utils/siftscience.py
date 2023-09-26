import functools
import json

import sift.client
from django.apps import apps
from ipware import get_client_ip

from researchhub.celery import QUEUE_EXTERNAL_REPORTING, app
from researchhub.settings import SIFT_ACCOUNT_ID, SIFT_REST_API_KEY
from utils import sentry

# https://sift.com/resources/guides/content-abuse

client = sift.Client(api_key=SIFT_REST_API_KEY, account_id=SIFT_ACCOUNT_ID)

SIFT_COMMENT = "track_content_comment"
SIFT_PAPER = "track_content_paper"
SIFT_POST = "track_content_post"
SIFT_VOTE = "track_content_vote"


def get_user_score(user_id):
    try:
        response = client.score(user_id)
        out = json.dumps(response.body)
        print(out)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e.api_error_message)


def label_bad_user(user_id, abuse_type, description=""):
    # TODO: Finish this by determing how we plan to use it
    try:
        response = client.label(
            user_id,
            {
                "$is_bad": True,
                # optional fields
                "$abuse_type": abuse_type,
                "$description": description,
                "$source": "django",
                "$analyst": "dev@quantfive.org",
            },
        )
        print(response.body)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e.api_error_message)


def unlabel_user(user_id):
    # TODO: Finish this by determing how we plan to use it
    try:
        response = client.unlabel(user_id, abuse_type="content_abuse")
        print(response.body)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e.api_error_message)


def get_tracked_content_score(tracked_content):
    score_response = tracked_content.get("score_response", None)
    if score_response:
        score = score_response["scores"]["content_abuse"]["score"]
        score = round(score * 100, 1)
        return score
    return None


def update_user_risk_score(user, tracked_content):
    if tracked_content:
        content_risk_score = get_tracked_content_score(tracked_content)
        if content_risk_score:
            user.sift_risk_score = content_risk_score
            user.save(update_fields=["sift_risk_score"])
            check_user_risk(user)


def check_user_risk(user):
    sift_risk_score = user.sift_risk_score
    if sift_risk_score and sift_risk_score > 90:
        user.set_suspended(is_manual=False)


class DecisionsApi:
    def apply_bad_user_decision(
        self, content_creator, source="AUTOMATED_RULE", reporter=None
    ):
        applyDecisionRequest = {
            "decision_id": "looks_bad_content_abuse",
            "source": source,
            "analyst": reporter.email if reporter else "analyst@researchhub.com",
            "description": "User looks risky for content abuse",
            "reason": "User looks risky for content abuse",
        }

        try:
            client.apply_user_decision(str(content_creator.id), applyDecisionRequest)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e)

    def apply_bad_content_decision(
        self, content_creator, content_id, source="AUTOMATED_RULE", reporter=None
    ):
        applyDecisionRequest = {
            "decision_id": "content_looks_bad_content_abuse",
            "source": source,
            "analyst": reporter.email if reporter else "analyst@researchhub.com",
            "description": "Auto flag of moderator-removed content",
            "reason": "Auto flag of moderator-removed content",
        }

        try:
            client.apply_content_decision(
                str(content_creator.id), content_id, applyDecisionRequest
            )
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e)


class EventsApi:
    def create_meta_properties(self, request, exclude_ip=False):
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        properties = {"$browser": {"$user_agent": user_agent}}

        if not exclude_ip:
            ip, is_routable = get_client_ip(request)
            if ip:
                properties["ip"] = ip
        return properties

    @staticmethod
    @app.task
    def celery_track_account(user_id, meta, update):
        User = apps.get_model("user.User")
        user = User.objects.get(id=user_id)

        properties = {
            # Required Fields
            "$user_id": str(user.id),
            # Supported Fields
            "$user_email": user.email,
            "$name": f"{user.first_name} {user.last_name}",
            "$social_sign_on_type": "$google",
        }
        track_type = "$update_account" if update else "$create_account"

        try:
            response = client.track(track_type, properties, return_score=False)
            print(response.body)
            return response.body
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_account(self, user, request, update=False):
        meta = self.create_meta_properties(request, exclude_ip=True)
        celery_response = self.celery_track_account.apply(
            (user.id, meta, update),
            priority=4,
            countdown=10,
        )
        tracked_account = celery_response.get()
        return tracked_account

    def track_login(self, user, login_status, request):
        # https://sift.com/developers/docs/python/events-api/reserved-events/login
        meta = self.create_meta_properties(request)
        celery_response = self.celery_track_login.apply(
            (user.id, meta, login_status), priority=4, countdown=10
        )
        tracked_login = celery_response.get()
        return tracked_login

    @staticmethod
    @app.task
    def celery_track_login(user_id, meta, login_status):
        User = apps.get_model("user.User")
        user = User.objects.get(id=user_id)

        properties = {
            "$user_id": str(user.id),
            "$login_status": login_status,
            "$username": user.username,
        }

        try:
            response = client.track("$login", properties, return_score=False)
            print(response.body)
            return response.body
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_content_comment(self, request, response_data, is_update):
        meta = self.create_meta_properties(request)
        celery_response = self.celery_track_content_comment.apply_async(
            (
                response_data,
                meta,
                is_update,
            ),
            priority=4,
            countdown=3,
        )
        return celery_response

    @staticmethod
    @app.task(queue=QUEUE_EXTERNAL_REPORTING)
    def celery_track_content_comment(response_data, meta, update):
        User = apps.get_model("user.User")
        RhComment = apps.get_model("researchhub_comment.RhCommentModel")

        created_by = response_data["created_by"]
        user_id = str(created_by["id"])
        user = User.objects.get(id=user_id)

        thread = response_data["thread"]
        obj_name = thread["content_type"]["model"]
        obj_id = thread["object_id"]

        root_content_id = f"{obj_name}_{obj_id}"
        rh_comment = RhComment.objects.get(id=response_data["id"])
        content_id = f"{type(rh_comment).__name__}_{response_data['id']}"

        comment_properties = {
            # Required fields
            "$user_id": user_id,
            # must be unique across all content types
            "$content_id": content_id,
            # Recommended fields
            "$status": "$active",
            # Required $comment object
            "$comment": {
                "$body": rh_comment.plain_text,
                "$contact_email": user.email,
                "$root_content_id": root_content_id,
            },
            **meta,
        }
        if rh_comment_parent := rh_comment.parent:
            comment_properties["$comment"][
                "$parent_comment_id"
            ] = f"{type(rh_comment_parent).__name__}_{rh_comment_parent.id}"

        track_type = "$update_content" if update else "$create_content"

        try:
            response = client.track(track_type, comment_properties, return_score=False)
            print(response.body)
            return response.body
        except sift.client.ApiException as e:
            sentry.log_error(e)

    def track_content_paper(self, request, response_data, is_update):
        meta = self.create_meta_properties(request)
        celery_response = self.celery_track_content_paper.apply_async(
            (response_data, meta, is_update),
            priority=4,
            countdown=5,
        )
        return celery_response

    @staticmethod
    @app.task(queue=QUEUE_EXTERNAL_REPORTING)
    def celery_track_content_paper(response_data, meta, update):
        User = apps.get_model("user.User")
        Paper = apps.get_model("paper.Paper")

        paper_id = response_data["id"]
        paper = Paper.objects.get(id=paper_id)

        created_by = response_data["uploaded_by"]
        user_id = str(created_by["id"])
        user = User.objects.get(id=user_id)

        post_properties = {
            # Required fields
            "$user_id": user_id,
            "$content_id": f"{type(paper).__name__}_{paper.id}",
            # Recommended fields
            "$status": "$active",
            # Required $post object
            "$post": {
                "$subject": paper.title,
                "$body": paper.abstract,
                "$contact_email": user.email,
                "$contact_address": {
                    "$name": f"{user.first_name} {user.last_name}",
                },
                "$categories": list(paper.hubs.values_list("slug", flat=True)),
            },
            **meta,
        }

        track_type = "$update_content" if update else "$create_content"

        try:
            response = client.track(track_type, post_properties, return_score=False)
            return response.body
        except sift.client.ApiException as e:
            sentry.log_error(e)

    def track_content_vote(self, user, vote, request, update=False):
        meta = self.create_meta_properties(request)
        vote_type = vote.__module__.split(".")[0]
        celery_response = self.celery_track_content_vote.apply(
            (user.id, vote.id, vote_type, meta, update), priority=4, countdown=10
        )
        tracked_vote = celery_response.get()
        return tracked_vote

    @staticmethod
    @app.task
    def celery_track_content_vote(user_id, vote_id, vote_type, meta, update):
        User = apps.get_model("user.User")
        user = User.objects.get(id=user_id)
        Vote = apps.get_model(f"{vote_type}.Vote")
        vote = Vote.objects.get(id=vote_id)
        rating = vote.vote_type

        review_properties = {
            "$user_id": str(user.id),
            "$content_id": f"{type(vote).__name__}_{vote.id}",
            "$status": "$active",
            "$review": {"$contact_email": user.email, "$rating": rating},
        }
        track_type = "$update_content" if update else "$create_content"

        try:
            response = client.track(track_type, review_properties, return_score=False)
            print(response.body)
            return response.body
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_flag_content(self, user, content_id, referer_id):
        # https://sift.com/developers/docs/curl/events-api/reserved-events/flag-content
        if not user:
            return None
        properties = {
            "$user_id": str(user.id),
            "$content_id": content_id,
            "$flagged_by": str(referer_id),
        }

        try:
            response = client.track("$flag_content", properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e.api_error_message)

    def track_content_status(self):
        # https://sift.com/developers/docs/python/events-api/reserved-events/content-status
        # TODO: We might not need this?
        properties = {"$user_id": "", "$content_id": "", "$status": ""}


events_api = EventsApi()

decisions_api = DecisionsApi()


def sift_track(track_type, is_update=False):
    def decorator(func):
        @functools.wraps(func)
        def inner(class_, request, *args, **kwargs):
            res = func(class_, request, *args, **kwargs)
            try:
                sift_func = getattr(events_api, track_type)
                sift_func(request, res.data, is_update)
                # if res.status_code >= 200 and res.status_code <= 299 and not DEVELOPMENT:
            except Exception as e:
                print(e)
                # log_info(e, getattr(amp, "hit", None))
            return res

        return inner

    return decorator

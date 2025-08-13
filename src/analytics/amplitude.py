import functools
import json

import requests

from researchhub.settings import AMPLITUDE_API_KEY, DEVELOPMENT
from utils.parsers import json_serial
from utils.sentry import log_error, log_info


class Amplitude:
    api_key = AMPLITUDE_API_KEY
    api_url = "https://api.amplitude.com/2/httpapi"

    def _build_event_properties(self, view):
        data = view.__dict__
        event_type = f"{data['basename']}_{data['action']}"
        return event_type

    def _build_user_properties(self, user):
        if user.is_anonymous:
            user_properties = {
                "email": "",
                "first_name": "Anonymous",
                "last_name": "Anonymous",
                "reputation": 0,
                "is_suspended": False,
                "probable_spammer": False,
                "invited_by_id": 0,
                "is_hub_editor": False,
                "is_verified": False,
            }
            user_id = ""
        else:
            invited_by = user.invited_by
            if invited_by:
                invited_by = invited_by.id
            user_properties = {
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "reputation": user.reputation,
                "is_suspended": user.is_suspended,
                "probable_spammer": user.probable_spammer,
                "invited_by_id": invited_by,
                "is_hub_editor": user.is_hub_editor(),
                "is_verified": user.is_verified,
            }
            user_id = f"{user.id:0>6}"
        return user_id, user_properties

    def build_hit(self, res, view, request, *args, **kwargs):
        user = request.user
        user_id, user_properties = self._build_user_properties(user)
        event_type = self._build_event_properties(view)
        data = {
            "user_id": user_id,
            "event_type": event_type,
            "user_properties": user_properties,
        }

        res_data = res.data
        if isinstance(res_data, dict):
            data["event_properties"] = res_data
        else:
            data["event_properties"] = {"data": res_data}

        if res_id := getattr(res_data, "id", None):
            data["insert_id"] = f"{event_type}_{res_id}"

        if extra_data := getattr(res, "amplitude_data", None):
            data["event_properties"].update(extra_data)

        hit = {
            "api_key": self.api_key,
            "events": [data],
        }
        hit = json.dumps(hit, default=json_serial)
        return self.forward_event(hit)

    def _track_revenue_event(
        self,
        user,
        revenue_type: str,
        rsc_revenue: str,
        usd_revenue: str,
        additional_properties: dict = {},
    ):
        user_id, user_properties = self._build_user_properties(user)
        data = {
            "user_id": user_id,
            "event_type": "revenue",
            "user_properties": user_properties,
            "event_properties": {
                "revenue_type": revenue_type,
                "rsc_revenue": rsc_revenue,
                "usd_revenue": usd_revenue,
                **additional_properties,
            },
            # Amplitude has specific revenue properties that we can use.
            "revenue": usd_revenue,
            "revenueType": revenue_type,
        }
        hit = {
            "api_key": self.api_key,
            "events": [data],
        }
        hit = json.dumps(hit, default=json_serial)
        return self.forward_event(hit)

    def _track_user_activity_event(
        self,
        user,
        activity_type: str,
        additional_properties: dict = {},
    ):
        """
        Track user activity events for analytics funnel.

        Args:
            user: User instance
            activity_type: Type of activity (upvote, comment, peer_review, fund, tip, journal_submission)
            additional_properties: Additional properties to include in the event
        """
        user_id, user_properties = self._build_user_properties(user)

        valid_user_id = _ensure_valid_user_id(user_id)

        data = {
            "user_id": valid_user_id,
            "event_type": "user_activity",
            "user_properties": user_properties,
            "event_properties": {
                "activity_type": activity_type,
                **additional_properties,
            },
        }
        hit = {
            "api_key": self.api_key,
            "events": [data],
        }
        hit = json.dumps(hit, default=json_serial)
        return self.forward_event(hit)

    def forward_event(self, hit):
        headers = {"Content-Type": "application/json", "Accept": "*/*"}
        request = requests.post(self.api_url, data=hit, headers=headers)
        res = request.json()
        if request.status_code != 200:
            log_info(res)
        return res


def track_event(func):
    @functools.wraps(func)
    def inner(*args, **kwargs):
        res = func(*args, **kwargs)
        amp = None

        try:
            if res.status_code >= 200 and res.status_code <= 299 and not DEVELOPMENT:
                amp = Amplitude()
                amp.build_hit(res, *args, **kwargs)

                # Auto-detect and track user activities based on event type
                _auto_track_user_activity_by_event_type(res, *args, **kwargs)
        except Exception as e:
            log_error(
                e,
                message="Failed to track amplitude event",
                json_data={"amp_hit": getattr(amp, "hit", None)},
            )
        return res

    return inner


def _auto_track_user_activity_by_event_type(res, *args, **kwargs):
    """
    Automatically detect and track user activities based on generated event type.
    """
    if len(args) < 2:  # Need at least self and request
        return

    view = args[0]  # self
    request = args[1]  # request

    if not hasattr(request, "user") or request.user.is_anonymous:
        return

    user = request.user

    # Generate event type using existing logic
    amp = Amplitude()
    event_type = amp._build_event_properties(view)

    # Define event type to user activity mapping
    event_to_activity_mapping = {
        # Upvotes
        "paper_upvote": {
            "activity_type": UserActivityTypes.UPVOTE,
            "properties": lambda: {
                "content_type": "paper",
                "object_id": _get_object_id_from_response(res),
            },
        },
        "rh_comments_upvote": {
            "activity_type": UserActivityTypes.UPVOTE,
            "properties": lambda: {
                "content_type": "rhcommentmodel",
                "object_id": _get_object_id_from_response(res),
            },
        },
        "review_upvote": {
            "activity_type": UserActivityTypes.UPVOTE,
            "properties": lambda: {
                "content_type": "review",
                "object_id": _get_object_id_from_response(res),
            },
        },
        "researchhubpost_upvote": {
            "activity_type": UserActivityTypes.UPVOTE,
            "properties": lambda: {
                "content_type": "researchhubpost",
                "object_id": _get_object_id_from_response(res),
            },
        },
        # Comments (excluding peer review comments)
        "rh_comments_create_rh_comment": {
            "activity_type": UserActivityTypes.COMMENT,
            "condition": lambda: _is_public_comment(res),
            "properties": lambda: {
                "comment_id": res.data.get("id"),
                "comment_type": res.data.get("comment_type"),
                "thread_id": res.data.get("thread"),
            },
        },
        # Reviews
        "review_create": {
            "activity_type": UserActivityTypes.PEER_REVIEW,
            "properties": lambda: {
                "review_id": res.data.get("id"),
                "score": res.data.get("score"),
                "content_type": res.data.get("content_type"),
                "object_id": res.data.get("object_id"),
            },
        },
        # ResearchHub paper creation
        "paper_create_researchhub_paper": {
            "activity_type": UserActivityTypes.JOURNAL_SUBMISSION,
            "properties": lambda: {
                "submission_id": res.data.get("id"),
                "paper_status": "researchhub_paper",
                "title": res.data.get("title"),
            },
        },
        # Fundraise contributions
        "fundraise_create_contribution": {
            "activity_type": UserActivityTypes.FUND,
            "properties": lambda: {
                "purchase_id": _get_purchase_id_from_response(res),
                "amount": _get_amount_from_response(res),
                "content_type": "fundraise",
                "object_id": kwargs.get("pk"),
            },
        },
        # Tips/Boosts (Purchase with BOOST type)
        "purchase_create": {
            "activity_type": UserActivityTypes.TIP,
            "condition": lambda: _is_boost_purchase(res),
            "properties": lambda: {
                "purchase_id": res.data.get("id"),
                "amount": res.data.get("amount"),
                "purchase_type": res.data.get("purchase_type"),
                "content_type": res.data.get("content_type"),
                "object_id": res.data.get("object_id"),
            },
        },
    }

    # Check if this event type should trigger user activity tracking
    if event_type in event_to_activity_mapping:
        mapping = event_to_activity_mapping[event_type]

        # Check condition if it exists
        if "condition" in mapping:
            if not mapping["condition"]():
                return

        # Track the user activity
        _track_activity(user, mapping["activity_type"], mapping["properties"]())


def _track_activity(user, activity_type, properties):
    """Helper to track user activity"""
    try:
        track_user_activity(user, activity_type, properties)
    except Exception as e:
        log_error(e, message=f"Failed to auto-track {activity_type}")


def _is_public_comment(res):
    """Check if comment is public (not peer review or review)"""
    return (
        res.data.get("is_public", True)
        and not res.data.get("is_removed", False)
        and res.data.get("comment_type") not in ["PEER_REVIEW", "REVIEW"]
    )


def _is_boost_purchase(res):
    """Check if purchase is a boost/tip"""
    return res.data.get("purchase_type") == "BOOST"


def _get_object_id_from_response(res):
    """Extract object ID from response"""
    return res.data.get("id")


def _get_purchase_id_from_response(res):
    """Extract purchase ID from fundraise contribution response"""
    # This might need adjustment based on actual response structure
    return res.data.get("purchase_id") or res.data.get("id")


def _get_amount_from_response(res):
    """Extract amount from response"""
    return res.data.get("amount")


class UserActivityTypes:
    UPVOTE = "upvote"
    COMMENT = "comment"
    PEER_REVIEW = "peer_review"
    FUND = "fund"
    TIP = "tip"
    JOURNAL_SUBMISSION = "journal_submission"


def track_user_activity(user, activity_type: str, additional_properties: dict = None):
    """
    Track user activity

    Args:
        user: User instance
        activity_type: Type of activity from UserActivityTypes
        additional_properties: Additional properties to include in the event
    """
    if not user or user.is_anonymous:
        return

    if additional_properties is None:
        additional_properties = {}

    try:
        if not DEVELOPMENT:
            amp = Amplitude()
            amp._track_user_activity_event(user, activity_type, additional_properties)
    except Exception as e:
        log_error(
            e,
            message="Failed to track user activity event",
            json_data={
                "user_id": user.id,
                "activity_type": activity_type,
                "additional_properties": additional_properties,
            },
        )


def _ensure_valid_user_id(user_id):
    """
    Ensure user ID meets Amplitude's minimum 6 character requirement.

    Args:
        user_id: Original user ID (can be int or str)

    Returns:
        str: User ID padded to at least 6 characters
    """
    user_id_str = str(user_id)

    # If already 6+ characters, return as is
    if len(user_id_str) >= 6:
        return user_id_str

    # Pad with leading zeros to reach 6 characters
    # e.g., 123 -> "000123", 45 -> "000045"
    return user_id_str.zfill(6)

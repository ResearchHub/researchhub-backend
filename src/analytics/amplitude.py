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
            user_id = "_Anonymous_"
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
                "is_verified": user.is_verified_v2,
            }
            user_id = f"user: {user.email}_{user.id}"
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
        except Exception as e:
            log_error(
                e,
                message="Failed to track amplitude event",
                json_data={"amp_hit": getattr(amp, "hit", None)},
            )
        return res

    return inner


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

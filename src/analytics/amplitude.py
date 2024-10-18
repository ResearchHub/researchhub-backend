import functools
import json

import requests

from researchhub.settings import AMPLITUDE_API_KEY, DEVELOPMENT
from utils.parsers import json_serial
from utils.sentry import log_info


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
                "is_verified": user.is_verified,
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
            log_info(e, getattr(amp, "hit", None))
        return res

    return inner

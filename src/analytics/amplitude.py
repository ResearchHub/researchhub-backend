import functools
import json

import requests
from typing import Literal
from ipware import get_client_ip

from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
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

    # DEPRECATED
    # Requires geolocation data from frontend
    def DEPRECATED_build_geo_properties(self, request):
        ip, is_routable = get_client_ip(request)
        data = {}
        try:
            geo_info = geo.city(ip)
            data["ip"] = ip
            data["country"] = geo_info["country_name"]
            data["city"] = geo_info["city"]
            data["region"] = geo_info["region"]
            data["dma"] = geo_info["dma_code"]
            data["location_lat"] = geo_info["latitude"]
            data["location_lng"] = geo_info["longitude"]
        except Exception as e:
            log_info(e)
            return {}
        return data

    def build_hit(self, res, view, request, *args, **kwargs):
        user = request.user
        user_id, user_properties = self._build_user_properties(user)
        event_type = self._build_event_properties(view)
        # geo_properties = self._build_geo_properties(request)
        data = {
            "user_id": user_id,
            "event_type": event_type,
            "user_properties": user_properties,
            # **geo_properties,
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
    
    def track_revenue_event(
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


def track_revenue_event(
    user,
    revenue_type: Literal["BOUNTY_FEE", "FUNDRAISE_CONTRIBUTION_FEE", "SUPPORT_FEE", "DOI_FEE", "WITHDRAWAL_FEE"],
    rsc_revenue: str,
    usd_revenue: str = None,
    transaction_method: Literal["OFF_CHAIN", "ON_CHAIN", "STRIPE"] = None,

    # it's useful to be able to see e.g. how much did we make on paper tips versus comment tips.
    # so we should use these fields to point to the object that the revenue is associated with.
    # and not simply the Purchase/Balance/Fundraise object.
    content_type: str = None,
    object_id: str = None,

    additional_properties: dict = {},
):
    """
    Helper function to track revenue events.
    Performs the conversion from RSC to USD if usd_revenue is None.
    """

    amp = None
    if DEVELOPMENT:
        return

    try:
        if usd_revenue is None:
            if not isinstance(rsc_revenue, float):
                rsc_revenue_float = float(rsc_revenue)
            else:
                rsc_revenue_float = rsc_revenue

            usd_revenue_float = RscExchangeRate.rsc_to_usd(rsc_revenue_float)
            usd_revenue = str(usd_revenue_float)
    except Exception as e:
        log_info("Error converting RSC to USD", e)

    try:
        additional_properties["transaction_method"] = transaction_method
        additional_properties["content_type"] = content_type
        additional_properties["object_id"] = object_id

        amp = Amplitude()
        amp.track_revenue_event(
            user,
            revenue_type,
            rsc_revenue,
            usd_revenue,
            additional_properties,
        )
    except Exception as e:
        log_info(e, getattr(amp, "revenue_event", None))

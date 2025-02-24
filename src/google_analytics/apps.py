from urllib.parse import urlencode

from django.apps import AppConfig
from django.utils import timezone

from google_analytics.exceptions import GoogleAnalyticsError
from researchhub.settings import PRODUCTION, TESTING
from utils.http import POST, http_request

TRACKING_ID = "UA-106669204-1"
USER_ID = "django"
USER_AGENT = "Opera/9.80"  # Use any valid user agent to be safe


class GoogleAnalyticsConfig(AppConfig):
    name = "google_analytics"

    def ready(self):
        # Disabling google analytics
        # import google_analytics.signals  # noqa: F401
        return


class GoogleAnalytics:
    def send_hit(self, hit):
        """
        Returns an http response after constructing a urlencoded payload for
        `hit` and sending it to Google Analytics.
        """
        data = self.build_hit_urlencoded(hit)
        return self._send_hit_data(data)

    def send_batch_hits(self, hits):
        """
        Args:
            hit_data (:list:`str`) -- List of urlencoded hit payloads. Max 20.

        Each hit payload in `hit_data` must be no more than 8K bytes. The total
        size of all payloads must be no more than 16K bytes.
        """
        if len(hits) > 20:
            raise GoogleAnalyticsError(ValueError, "Exceeds 20 hits")

        hit_data = []
        for hit in hits:
            payload = self.build_hit_urlencoded(hit)
            if len(payload.encode("utf-8")) > 8000:
                raise GoogleAnalyticsError(ValueError, "Exceeds 8k bytes per hit")
            hit_data.append(self.build_hit_urlencoded(hit))

        data = "\n".join(hit_data)
        if len(data.encode("utf-8")) > 16000:
            raise GoogleAnalyticsError(ValueError, "Exceeds 16k bytes")

        return self._send_hit_data(data, batch=True)

    def build_hit_urlencoded(self, hit):
        """
        Returns urlencoded string of hit and GA fields.
        """
        hit_fields = hit.fields
        optional_fields = {
            "npa": 1,  # Exclude from ad personalization
            "ds": "django",  # Data source
            "qt": self.get_queue_time(hit.hit_datetime),  # Ms since hit occurred # noqa
            "ni": 0,  # Non-interactive
        }
        fields = {
            "v": 1,  # GA protocol version
            "t": hit.hit_type,
            "tid": TRACKING_ID,
            "cid": USER_ID,
            "ua": USER_AGENT,
            **optional_fields,
            **hit_fields,
        }
        return urlencode(fields)

    def get_queue_time(self, dt):
        """
        Returns milliseconds (`int`) since `dt`.
        """
        if dt is None:
            return 0

        if dt.tzinfo is None:
            dt = timezone.make_aware(dt)

        delta = timezone.now() - dt
        return int(delta.total_seconds() * 1000)

    def _send_hit_data(self, data, batch=False):

        base_url = "https://www.google-analytics.com/"
        if not PRODUCTION:
            base_url += "debug/"
            error = GoogleAnalyticsError(UserWarning, "Sending event to debugger")
            if TESTING:
                return
            else:
                print(error)

        url = base_url + "collect"
        if batch:
            url = base_url + "batch"

        return http_request(POST, url, data=data)


class Hit:
    """
    Hit data for Google Analytics measurement protocol.

    For details see
    https://developers.google.com/analytics/devguides/collection/protocol/v1

    Args:
        hit_type (str)
        hit_datetime (obj) -- None converts to the time the hit is sent
        fields (dict)
    """

    EVENT = "event"

    def __init__(self, hit_type, hit_datetime, fields):
        self.hit_type = hit_type
        self.hit_datetime = hit_datetime
        self.fields = fields

    def build_event_fields(category=None, action=None, label=None, value=None):
        """
        Args:
            category (str)
            action (str)
            label (str)
            value (int)
        """
        fields = {}
        fields["ec"] = category
        fields["ea"] = action
        fields["el"] = label
        fields["ev"] = value
        return fields

    def get_required_fields(self, hit_type):
        if hit_type == self.EVENT:
            return {
                "ec": None,  # Category
                "ea": None,  # Action
                "el": None,  # Label
                "ev": None,  # Value
            }

from google_analytics.apps import GoogleAnalytics, Hit

from researchhub.settings import PRODUCTION


ga = GoogleAnalytics()


def get_event_hit_response(
    category,
    action,
    label,
    utc_datetime,
    value=0
):
    if not PRODUCTION:
        category = 'Test ' + category
    fields = Hit.build_event_fields(
        category=category,
        action=action,
        label=label,
        value=value
    )
    hit = Hit(Hit.EVENT, utc_datetime, fields)
    return ga.send_hit(hit)

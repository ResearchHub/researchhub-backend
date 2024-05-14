from researchhub.settings import (
    ASSETS_BASE_URL,
    BASE_FRONTEND_URL,
)


class NotificationFrequencies:
    IMMEDIATE = 0
    DAILY = 1440
    THREE_HOUR = 180
    WEEKLY = 10080


base_email_context = {
    "assets_base_url": ASSETS_BASE_URL,
    "opt_out": BASE_FRONTEND_URL + "/email/opt-out/",
    "update_subscription": BASE_FRONTEND_URL + "/user/settings/",
}

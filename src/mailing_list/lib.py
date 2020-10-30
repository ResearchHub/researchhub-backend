from researchhub.settings import BASE_FRONTEND_URL


class NotificationFrequencies:
    IMMEDIATE = 0
    DAILY = 1440
    THREE_HOUR = 180
    WEEKLY = 10080


base_email_context = {
    'opt_out': BASE_FRONTEND_URL + '/email/opt-out/',
    'update_subscription': BASE_FRONTEND_URL + '/user/settings/'
}

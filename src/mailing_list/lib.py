class NotificationFrequencies:
    IMMEDIATE = 0
    DAILY = 1440
    THREE_HOUR = 180


# TODO: Change base_url for testing

base_url = 'researchhub.com'

base_email_context = {
    'opt_out': base_url + '/email/opt-out/'
}

from django.conf import settings

STRIPE_API_VERSION = "2024-09-30.acacia"
"""
The Strip API version to use for all requests.
"""


def get_stripe():
    """
    Returns the configured Stripe module.
    """
    import stripe  # delay until needed

    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = STRIPE_API_VERSION

    return stripe

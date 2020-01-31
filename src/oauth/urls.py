from rest_auth.urls import urlpatterns as default_urls
from rest_auth.registration.urls import urlpatterns as registration_urls
from allauth.socialaccount.urls import urlpatterns as social_account_urls

with_default = (
    default_urls
    + registration_urls
    + social_account_urls
)

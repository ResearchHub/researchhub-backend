from rest_auth.urls import urlpatterns as default_urls
from rest_auth.registration.urls import urlpatterns as registration_urls
from allauth.socialaccount.providers.google.urls import (
    urlpatterns as google_urls
)
from allauth.socialaccount.providers.orcid.urls import (
    urlpatterns as orcid_urls
)

with_default = default_urls + registration_urls + google_urls + orcid_urls

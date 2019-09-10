from allauth.account.urls import urlpatterns as default_urls
from allauth.socialaccount.providers.google.urls import urlpatterns as google_urls

with_default = default_urls + google_urls

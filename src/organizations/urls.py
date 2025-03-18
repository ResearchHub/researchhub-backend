from django.urls import path

from organizations.views import NonprofitFundraiseLinkViewSet, NonprofitOrgViewSet

# Create a direct URL pattern for the viewset's search action
urlpatterns = [
    # Direct path to the search endpoint
    path(
        "non-profit/search/",
        NonprofitOrgViewSet.as_view({"get": "search"}),
        name="nonprofit-orgs-search",
    ),
    # Endpoints for nonprofit-fundraise linking
    path(
        "non-profit/create/",
        NonprofitFundraiseLinkViewSet.as_view({"post": "create_nonprofit"}),
        name="nonprofit-create",
    ),
    path(
        "non-profit/link-to-fundraise/",
        NonprofitFundraiseLinkViewSet.as_view({"post": "link_to_fundraise"}),
        name="nonprofit-link-to-fundraise",
    ),
]

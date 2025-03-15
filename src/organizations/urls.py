from django.urls import path

from organizations.views import NonprofitOrgViewSet

# Create a direct URL pattern for the viewset's search action
urlpatterns = [
    # Direct path to the search endpoint
    path(
        "non-profit/search/",
        NonprofitOrgViewSet.as_view({"get": "search"}),
        name="nonprofit-orgs-search",
    ),
]

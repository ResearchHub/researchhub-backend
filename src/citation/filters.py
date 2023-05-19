from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from citation.models import CitationEntry, CitationProject
from user.related_models.organization_model import Organization


class CitationEntryFilter(filters.FilterSet):
    organization_id = filters.NumberFilter(
        method="filter_by_org",
        label="Organization Id",
    )
    project_id = filters.NumberFilter(
        method="filter_by_proj",
        label="Project Id",
    )
    get_current_user_citations = filters.NumberFilter(
        method="filter_by_user_citations", label="User Created Citations"
    )

    class Meta:
        model = CitationEntry
        fields = ("organization_id", "project_id")

    def filter_by_org(self, qs, name, value):
        org = Organization.objects.filter(id=value)
        if org.exists():
            return org.first().created_citations.all()
        raise ValidationError("Organization does not exist")

    def filter_by_proj(self, qs, name, value):
        citation_project = CitationProject.objects.filter(id=value)
        if citation_project.exists():
            return citation_project.first().citations.all()
        raise ValidationError("Citation Project does not exist")

    def filter_by_user_citations(self, qs, name, value):
        if value:
            user = self.request.user
            return qs.filter(created_by=user)
        return qs

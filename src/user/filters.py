from django.db import models
from django_filters import rest_framework as filters
from django_filters import utils

from discussion.constants.flag_reasons import (
    VERDICT_FILTER_CHOICES,
    VERDICT_REMOVED,
    VERIDCT_APPROVED,
    VERIDCT_OPEN,
)
from discussion.reaction_models import Flag
from user.models import Action, User
from utils.filters import ListExcludeFilter

from .models import Author


class AuthorFilter(filters.FilterSet):
    id__ne = ListExcludeFilter(field_name="id")
    education = filters.CharFilter(lookup_expr="icontains")
    headline = filters.CharFilter(lookup_expr="icontains")

    class Meta:
        model = Author
        fields = [field.name for field in model._meta.fields]
        exclude = ["openalex_ids"]
        fields.append("id__ne")
        filter_overrides = {
            models.FileField: {
                "filter_class": filters.CharFilter,
            }
        }


class UserFilter(filters.FilterSet):
    invited_by = filters.NumberFilter()
    referral_code = filters.Filter()

    class Meta:
        model = User
        fields = []


class FlagDashboardFilter(filters.FilterSet):
    verdict = filters.ChoiceFilter(
        field_name="verdict", method="filter_by_verdict", choices=VERDICT_FILTER_CHOICES
    )

    class Meta:
        model = Flag
        fields = ["verdict", "hubs"]

    def filter_by_verdict(self, qs, name, value):
        filters = {}
        value = value.upper()
        if value == VERIDCT_OPEN:
            expr = f"{name}__isnull"
            filters[expr] = True
        elif value == VERIDCT_APPROVED:
            expr = f"{name}__is_content_removed"
            filters[expr] = False
        elif value == VERDICT_REMOVED:
            expr = f"{name}__is_content_removed"
            filters[expr] = True
        return qs.filter(**filters)


class ActionDashboardFilter(filters.FilterSet):
    class Meta:
        model = Action
        fields = ["hubs"]


class AuditDashboardFilterBackend(filters.DjangoFilterBackend):
    ordering_param = "ordering"

    def get_filterset_class(self, view, queryset=None):
        """
        Taken from django-filters source code
        """
        filterset_class = getattr(view, "filterset_class", None)
        filterset_fields = getattr(view, "filterset_fields", None)

        # Custom logic start
        if view.action == "flagged":
            filterset_class = FlagDashboardFilter
        else:
            filterset_class = ActionDashboardFilter
        # Custom logic end

        if filterset_class is None and hasattr(view, "filter_class"):
            utils.deprecate(
                "`%s.filter_class` attribute should be renamed `filterset_class`."
                % view.__class__.__name__
            )
            filterset_class = getattr(view, "filter_class", None)

        if filterset_fields is None and hasattr(view, "filter_fields"):
            utils.deprecate(
                "`%s.filter_fields` attribute should be renamed `filterset_fields`."
                % view.__class__.__name__
            )
            filterset_fields = getattr(view, "filter_fields", None)

        if filterset_class:
            filterset_model = filterset_class._meta.model

            # FilterSets do not need to specify a Meta class
            if filterset_model and queryset is not None:
                assert issubclass(
                    queryset.model, filterset_model
                ), "FilterSet model %s does not match queryset model %s" % (
                    filterset_model,
                    queryset.model,
                )

            return filterset_class

        if filterset_fields and queryset is not None:
            MetaBase = getattr(self.filterset_base, "Meta", object)

            class AutoFilterSet(self.filterset_base):
                class Meta(MetaBase):
                    model = queryset.model
                    fields = filterset_fields

            return AutoFilterSet

        return None

    def get_ordering(self, request, queryset, view):
        params = request.query_params.get(self.ordering_param)
        if params:
            valid_fields = []
            fields = [param.strip() for param in params.split(",")]
            for field in fields:
                order_param = field
                if order_param.startswith("-"):
                    order_param = order_param[1:]
                if order_param in view.order_fields:
                    valid_fields.append(field)

            if valid_fields:
                return valid_fields
        return ("-created_date",)

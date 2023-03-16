from django_filters import rest_framework as filters

from researchhub_comment.models import RhCommentThreadModel

BEST = "BEST"
TOP = "TOP"
CREATED_DATE = "CREATED_DATE"

ORDER_CHOICES = ((BEST, "Best"), (TOP, "Top"), (CREATED_DATE, "Created Date"))


class RHCommentFilter(filters.FilterSet):
    ordering = filters.ChoiceFilter(
        method="ordering_filter",
        choices=ORDER_CHOICES,
        null_value=BEST,
    )

    class Meta:
        model = RhCommentThreadModel
        fields = ("ordering",)

    def ordering_filter(self, qs, name, value):
        print(name, value)
        pass
        return qs


class DjangoFilterBackendWithComments(filters.DjangoFilterBackend):
    ordering_param = "ordering"

    def get_filterset_class(self, view, queryset=None):
        """
        Taken from django-filters source code
        """

        filterset_class = getattr(view, "filterset_class", None)
        filterset_fields = getattr(view, "filterset_fields", None)

        # Custom logic start
        thread_mixin_methods = getattr(view, "_THREAD_MIXIN_METHODS_", None)
        if thread_mixin_methods and view.action in thread_mixin_methods:
            filterset_class = RHCommentFilter
        # Custom logic end

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

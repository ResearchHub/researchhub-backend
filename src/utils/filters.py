from django.db.models import Case, Count, DecimalField, F, FloatField, Q, Sum, When
from django.db.models.functions import Cast, Coalesce, Ln
from django_filters import rest_framework as filters

from discussion.models import Vote
from purchase.models import Purchase
from user.related_models.user_verification_model import UserVerification

FIELD_LOOKUPS = (
    "exact",
    "iexact",
    "contains",
    "icontains",
    "in",
    "gt",
    "gte",
    "lt",
    "lte",
    "startswith",
    "istartswith",
    "endswith",
    "iendswith",
    "range",
    "date",
    "year",
    "iso_year",
    "month",
    "day",
    "week",
    "week_day",
    "quarter",
    "time",
    "hour",
    "minute",
    "second",
    "isnull",
    "regex",
    "iregex",
)


class ListExcludeFilter(filters.CharFilter):

    def __init__(self, **kwargs):
        super(ListExcludeFilter, self).__init__(**kwargs)

    def sanitize(self, value_list):
        """
        remove empty items in case of ?number=1,,2
        """
        return [v for v in value_list if v != ""]

    def customize(self, value):
        return value

    def filter(self, qs, value):
        multiple_vals = value.split(",")
        multiple_vals = self.sanitize(multiple_vals)
        multiple_vals = map(self.customize, multiple_vals)
        f = Q()
        for v in multiple_vals:
            kwargs = {self.field_name: v}
            f = f | Q(**kwargs)
        return qs.exclude(f)


class OrFilter(filters.CharFilter):
    """
    Syntax:

    ?or_filter=field1|field2|field3~value1,value2

    """

    def __init__(self, **kwargs):
        self.model = kwargs.pop("model", None)

        if self.model is None or not hasattr(self.model, "_meta"):
            raise ValueError("no model provided to or_filter")

        # Set field_name to or_filter if none provided
        if kwargs.get("field_name") is None:
            kwargs["field_name"] = "or_filter"

        super(OrFilter, self).__init__(**kwargs)

    def sanitize_keys(self, keys):
        """ """
        return [k for k in keys if self.is_valid_field(k)]

    def is_valid_field(self, key):
        return key != "" and self.get_field(key, self.model)

    def get_field(self, field, model):
        if "__" in field:
            if field[field.index("__") + 2 :] in FIELD_LOOKUPS:
                return self.get_field(field[: field.index("__")], model)
            return self.get_field(
                field[field.index("__") + 2 :],
                model._meta.get_field(field[: field.index("__")]).related_model,
            )
        else:
            return model._meta.get_field(field)

    def sanitize_values(self, value_list):
        """
        remove empty items in case of ~1,,2
        """
        return [v for v in value_list if v != ""]

    def sanitize_value(self, key, value):
        """ """
        if not value:
            raise ValueError("no value provided")

        internal_type = self.get_field(key, self.model).get_internal_type()
        if internal_type == "BooleanField":
            return value.lower() == "true"
        elif internal_type == "AutoField" or internal_type == "IntegerField":
            return int(value)
        else:
            return value

    def filter(self, qs, value):
        if value == "":
            return qs

        key_names, values = value.split("~")
        keys = key_names.split("|")

        sanitized_keys = self.sanitize_keys(keys)
        sanitized_values = self.sanitize_values(values.split(","))

        f = Q()
        for k in sanitized_keys:
            for v in sanitized_values:
                val = self.sanitize_value(k, v)
                or_expr = {k: val}
                f = f | Q(**or_expr)

        return qs.filter(f)


class QualityScoringMixin:
    def _annotate_best_score(self, qs):
        is_verified = Q(
            created_by__userverification__status=(UserVerification.Status.APPROVED)
        )
        is_quality_vote = Q(
            votes__created_by__is_suspended=False,
            votes__created_by__probable_spammer=False,
        )

        upvotes = Count(
            "votes", filter=is_quality_vote & Q(votes__vote_type=Vote.UPVOTE)
        )
        downvotes = Count(
            "votes", filter=is_quality_vote & Q(votes__vote_type=Vote.DOWNVOTE)
        )
        tips = Coalesce(
            Sum(
                Cast(
                    "purchases__amount",
                    DecimalField(max_digits=19, decimal_places=10),
                ),
                filter=Q(purchases__paid_status=Purchase.PAID),
            ),
            0,
            output_field=DecimalField(max_digits=19, decimal_places=10),
        )
        verified_boost = Case(
            When(is_verified, then=2.0), default=1.0, output_field=FloatField()
        )
        removed_penalty = Case(When(is_removed=True, then=-10000), default=0)

        return qs.annotate(
            upvotes=upvotes,
            downvotes=downvotes,
            tips=tips,
            verified_boost=verified_boost,
            removed_penalty=removed_penalty,
            quality_score=Cast(
                (F("upvotes") - F("downvotes")) * F("verified_boost")
                + F("tips") / 10.0
                + Ln(F("created_by__reputation") + 1)
                + F("removed_penalty"),
                FloatField(),
            ),
        )

    def _annotate_top_score(self, qs):  
        qs = self._annotate_best_score(qs) 
        return qs.annotate(
            top_primary_score=Cast(F("score") + F("removed_penalty"), FloatField()),
        )

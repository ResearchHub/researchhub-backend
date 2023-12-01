from django_filters import rest_framework as filters

from prediction_market.models import PredictionMarketVote


class PredictionMarketVoteFilter(filters.FilterSet):
    prediction_market_id = filters.NumberFilter(field_name="prediction_market__id")
    is_user_vote = filters.BooleanFilter(method="filter_by_user_vote")

    class Meta:
        model = PredictionMarketVote
        fields = ["prediction_market_id", "is_user_vote"]

    def filter_by_user_vote(self, queryset, name, value):
        if value:
            return queryset.filter(created_by=self.request.user)
        return queryset

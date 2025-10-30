import logging
import math
from typing import Union

from django.db.models import (
    Case,
    Count,
    DecimalField,
    DurationField,
    ExpressionWrapper,
    F,
    FloatField,
    QuerySet,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Extract, Greatest, Ln, Power
from django.utils import timezone

from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant

logger = logging.getLogger(__name__)

FUND_BEST_SCORE_CONFIG = {
    "signals": {
        "amount": {
            "weight": 40.0,
            "log_base": math.e,
            "description": "Total grant amount or funds raised (log-scaled to prevent mega-grants dominating)",
        },
        "applicants_contributors": {
            "weight": 50.0,
            "log_base": math.e,
            "description": "Number of applicants (grants) or contributors (fundraises)",
        },
        "comment": {
            "weight": 25.0,
            "log_base": math.e,
            "description": "Discussion activity on the post",
        },
        "upvote": {
            "weight": 15.0,
            "log_base": math.e,
            "description": "Community votes",
        },
    },
    "time_decay": {
        "gravity": 1.2,
        "base_hours": 2.0,
        "min_age_hours": 0.1,
    },
}
 
def calculate_fund_best_score_annotations(
    queryset: QuerySet,
    model_class: Union[type[Grant], type[Fundraise]],
) -> QuerySet:
    """Add best score annotations to a queryset of ResearchhubPost objects."""
    config = FUND_BEST_SCORE_CONFIG
    now = timezone.now()
    
    # Determine relationship paths and expressions for grants vs fundraises
    if model_class == Grant:
        relation_path = 'unified_document__grants'
        applicant_count_expr = Count(f'{relation_path}__applications', distinct=True)
        amount_expr = Coalesce(
            Sum(F(f'{relation_path}__amount')),
            Value(0),
            output_field=DecimalField(max_digits=19, decimal_places=2)
        )
    else:  # Fundraise
        relation_path = 'unified_document__fundraises'
        applicant_count_expr = Count(f'{relation_path}__purchases__user', distinct=True)
        amount_expr = Coalesce(
            Sum(F(f'{relation_path}__escrow__amount_holding') + F(f'{relation_path}__escrow__amount_paid')),
            Value(0),
            output_field=DecimalField(max_digits=19, decimal_places=10)
        )
    
    # Calculate age in hours
    age_duration = ExpressionWrapper(now - F('created_date'), output_field=DurationField())
    age_seconds = Extract(age_duration, 'epoch')
    age_hours_raw = ExpressionWrapper(age_seconds / 3600.0, output_field=FloatField())
    
    # Gather raw engagement metrics and age
    queryset = queryset.annotate(
        amount_value=amount_expr,
        upvote_count=Coalesce(F('unified_document__document_filter__upvoted_all'), Value(0)),
        comment_count=Coalesce(F('discussion_count'), Value(0)),
        applicant_contributor_count=applicant_count_expr,
        age_in_hours=Greatest(age_hours_raw, Value(config['time_decay']['min_age_hours'])),
    )
    
    # Calculate logarithmically-scaled signal components
    queryset = queryset.annotate(
        amount_component=ExpressionWrapper(
            Ln(F('amount_value') + Value(1.0)) * Value(config['signals']['amount']['weight']),
            output_field=FloatField()
        ),
        applicant_component=ExpressionWrapper(
            Ln(F('applicant_contributor_count') + Value(1.0)) * Value(config['signals']['applicants_contributors']['weight']),
            output_field=FloatField()
        ),
        comment_component=ExpressionWrapper(
            Ln(F('comment_count') + Value(1.0)) * Value(config['signals']['comment']['weight']),
            output_field=FloatField()
        ),
        upvote_component=ExpressionWrapper(
            Ln(F('upvote_count') + Value(1.0)) * Value(config['signals']['upvote']['weight']),
            output_field=FloatField()
        ),
    )
    
    # Sum signal components into total engagement score
    queryset = queryset.annotate(
        engagement_score=ExpressionWrapper(
            F('amount_component') + F('applicant_component') + F('comment_component') + F('upvote_component'),
            output_field=FloatField()
        )
    )
    
    # Apply time decay formula: score / (age + base)^gravity
    queryset = queryset.annotate(
        time_decay_denominator=Power(
            F('age_in_hours') + Value(config['time_decay']['base_hours']),
            Value(config['time_decay']['gravity'])
        ),
        best_score=ExpressionWrapper(
            (F('engagement_score') / F('time_decay_denominator')) * Value(100.0),
            output_field=FloatField()
        )
    )
    
    return queryset 
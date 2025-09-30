from django.db import models
from django.db.models import Sum, Exists, OuterRef, Case, When, DecimalField, Value
from django.db.models.functions import Cast


class CommentQuerySet(models.QuerySet):
    def with_academic_scores(self):
        """Annotate queryset with components needed for academic scoring."""
        from purchase.models import Purchase
        from reputation.models import BountySolution
        from user.models import User, UserVerification
        
        return self.annotate(
            tip_amount=Sum(
                Case(
                    When(
                        purchases__purchase_type=Purchase.BOOST,
                        purchases__paid_status=Purchase.PAID,
                        then=Cast('purchases__amount', DecimalField(max_digits=19, decimal_places=10))
                    ),
                    default=Value(0),
                    output_field=DecimalField(max_digits=19, decimal_places=10)
                )
            ),
            bounty_award_amount=Sum(
                Case(
                    When(
                        bounty_solution__status=BountySolution.Status.AWARDED,
                        then='bounty_solution__awarded_amount'
                    ),
                    default=Value(0),
                    output_field=DecimalField(max_digits=19, decimal_places=10)
                )
            ),
            is_verified_user=Exists(
                User.objects.filter(
                    id=OuterRef('created_by_id'),
                    userverification__status=UserVerification.Status.APPROVED
                )
            )
        )


class CommentManager(models.Manager):
    def get_queryset(self):
        return CommentQuerySet(self.model, using=self._db)
    
    def with_academic_scores(self):
        return self.get_queryset().with_academic_scores()
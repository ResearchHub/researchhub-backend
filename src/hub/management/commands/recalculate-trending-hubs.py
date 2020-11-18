from django.core.management.base import BaseCommand
from hub.models import Hub
from paper.utils import get_cache_key
from hub.serializers import HubSerializer

class Command(BaseCommand):

    def handle(self, *args, **options):
        # Math
        cache_key = get_cache_key(None, 'hubs', pk='trending')

        two_weeks_ago = timezone.now().date() - timedelta(days=14)
        num_upvotes = Count(
            'papers__vote__vote_type',
            filter=Q(
                papers__vote__vote_type=Vote.UPVOTE,
                papers__vote__created_date__gte=two_weeks_ago
            )
        )
        num_downvotes = Count(
            'papers__vote__vote_type',
            filter=Q(
                papers__vote__vote_type=Vote.DOWNVOTE,
                papers__vote__created_date__gte=two_weeks_ago
            )
        )
        # TODO: figure out bug with actions_past_two_weeks filter
        # actions_past_two_weeks = Count(
        #     'actions',
        #     filter=Q(
        #         actions__created_date__gte=two_weeks_ago,
        #         actions__user__isnull=False
        #     )
        # )
        paper_count = Count(
            'papers',
            filter=Q(
                papers__uploaded_date__gte=two_weeks_ago,
                papers__uploaded_by__isnull=False
            )
        )
        score = num_upvotes - num_downvotes
        score += paper_count
        qs = Hub.objects.filter(is_removed=False).annotate(
            score=score,
        ).order_by('-score')
        response = HubSerializer(qs, many=True).data
        cache.set(cache_key, response, timeout=60*60*24*7)
        
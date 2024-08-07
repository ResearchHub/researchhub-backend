from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce

from hub.models import Hub
from researchhub.celery import app


@app.task
def calculate_and_set_hub_counts():
    hubs = Hub.objects.annotate(
        total_paper_count=Count("related_documents"),
        posts_discussion_count=Sum("related_documents__posts__discussion_count"),
        paper_discussion_count=Sum("related_documents__paper__discussion_count"),
    ).annotate(
        # Combine the summed counts from posts and paper for total discussion count
        total_discussion_count=Coalesce(F("posts_discussion_count"), 0)
        + Coalesce(F("paper_discussion_count"), 0)
    )

    for hub in hubs.iterator():
        hub.paper_count = hub.total_paper_count
        hub.discussion_count = hub.total_discussion_count
        hub.save(update_fields=["paper_count", "discussion_count"])

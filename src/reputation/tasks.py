from django.contrib.contenttypes.models import ContentType

from researchhub.celery import app
from reputation.models import Contribution


@app.task
def create_contribution(contribution_type, user_id, paper_id, object_id):
    if contribution_type == Contribution.PAPER:
        content_type = ContentType.objects.get(
            app_label='paper',
            model='paper'
        )
    else:
        content_type = ContentType.objects.get(
            app_label='user',
            model='user'
        )

    previous_contributions = Contribution.objects.filter(
        contribution_type=contribution_type,
        content_type=content_type,
    ).order_by(
        'ordinal'
    )

    ordinal = 0
    if previous_contributions.exists():
        ordinal = previous_contributions.last().ordinal

    Contribution.objects.create(
        contribution_type=contribution_type,
        user=user_id,
        ordinal=ordinal,
        paper_id=paper_id,
        content_type=content_type,
        object_id=object_id
    )

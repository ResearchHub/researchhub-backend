import logging

from notification.models import Notification
from paper.openalex_util import process_openalex_works
from reputation.tasks import find_bounties_for_user_and_notify
from researchhub.celery import QUEUE_PULL_PAPERS, app
from researchhub.settings import TESTING
from user.related_models.user_model import User
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)


@app.task(queue=QUEUE_PULL_PAPERS)
def pull_openalex_author_works_batch(
    openalex_ids, user_id_to_notify_after_completion=None
):
    open_alex_api = OpenAlex()

    oa_ids = []
    for id_as_url in openalex_ids:
        just_id = id_as_url.split("/")[-1]
        oa_ids.append(just_id)

    # divide openalex_ids into chunks of 100
    # openalex api only allows 100 ids per request
    chunk_size = 100
    for i in range(0, len(oa_ids), chunk_size):
        chunk = oa_ids[i : i + chunk_size]
        works, _ = open_alex_api.get_works(openalex_ids=chunk)
        process_openalex_works(works)

    if user_id_to_notify_after_completion:
        user = User.objects.get(id=user_id_to_notify_after_completion)

        try:
            user.author_profile.calculate_hub_scores()
        except Exception:
            logger.exception("Failed to calculate hub scores for user %s", user.id)

        notification = Notification.objects.create(
            item=user,
            notification_type=Notification.PUBLICATIONS_ADDED,
            recipient=user,
            action_user=user,
        )

        notification.send_notification()

        if TESTING:
            find_bounties_for_user_and_notify(user.id)
        else:
            find_bounties_for_user_and_notify.apply_async(
                (user.id,), priority=3, countdown=1
            )

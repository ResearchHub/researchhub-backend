from datetime import timedelta

from celery.exceptions import MaxRetriesExceededError
from django.utils import timezone

from paper.openalex_util import process_openalex_works
from researchhub.celery import QUEUE_PULL_PAPERS, app
from researchhub.settings import PRODUCTION, TESTING
from utils import sentry
from utils.openalex import OpenAlex


@app.task(bind=True, max_retries=3)
def pull_new_openalex_works(self, retry=0, paper_fetch_log_id=None):
    from paper.models import PaperFetchLog

    return _pull_openalex_works(
        self, PaperFetchLog.FETCH_NEW, retry, paper_fetch_log_id
    )


@app.task(bind=True, max_retries=3)
def pull_updated_openalex_works(self, retry=0, paper_fetch_log_id=None):
    from paper.models import PaperFetchLog

    return _pull_openalex_works(
        self, PaperFetchLog.FETCH_UPDATE, retry, paper_fetch_log_id
    )


def _pull_openalex_works(self, fetch_type, retry=0, paper_fetch_log_id=None):
    from paper.models import PaperFetchLog

    """
    Pull works (papers) from OpenAlex.
    This looks complicated because we're trying to handle retries and logging.
    But simply:
    1. Get new or updated works from OpenAlex in batches
    2. Kick-off a task to create/update papers for each work
    3. If we hit an error, retry the job from where we left off
    4. Log the results
    """
    if not (PRODUCTION or TESTING):
        return

    date_to_fetch_from = timezone.now() - timedelta(days=1)
    # openalex uses a cursor to paginate through results,
    # cursor is meant to point to the next page of results.
    # if next_cursor = "*", it means it's the first page,
    # if next_cursor = None, it means it's the last page,
    # otherwise it's a base64 encoded string
    next_cursor = "*"

    total_papers_processed = 0

    # if paper_fetch_log_id is provided, it means we're retrying
    # otherwise we're starting a new pull
    if paper_fetch_log_id is None:
        start_date = timezone.now()

        # figure out when we should start fetching from.
        # if we have an existing successful run, we start from the last successful run
        try:
            last_successful_run_log = (
                PaperFetchLog.objects.filter(
                    source=PaperFetchLog.OPENALEX,
                    fetch_type=fetch_type,
                    status__in=[PaperFetchLog.SUCCESS, PaperFetchLog.FAILED],
                    journal=None,
                )
                .order_by("-started_date")
                .first()
            )
            if (
                last_successful_run_log
                and last_successful_run_log.status == PaperFetchLog.SUCCESS
            ):
                date_to_fetch_from = last_successful_run_log.started_date
            elif (
                last_successful_run_log
                and last_successful_run_log.status == PaperFetchLog.FAILED
            ):
                date_to_fetch_from = last_successful_run_log.fetch_since_date
                next_cursor = last_successful_run_log.next_cursor or "*"
        except Exception as e:
            sentry.log_error(e, message="Failed to get last successful or failed log")

        # check if there's a pending log within the last 24 hours
        # if there is, skip this run.
        # this is to prevent multiple runs from being queued at the same time,
        # since our celery setup sometimes triggers multiple runs
        try:
            pending_log = PaperFetchLog.objects.filter(
                source=PaperFetchLog.OPENALEX,
                fetch_type=fetch_type,
                status=PaperFetchLog.PENDING,
                started_date__gte=timezone.now() - timedelta(days=1),
                journal=None,
            ).exists()

            if pending_log:
                sentry.log_info(message="Pending log exists for updated works")
                return
        except Exception as e:
            sentry.log_error(e, message="Failed to get pending log")

        lg = PaperFetchLog.objects.create(
            source=PaperFetchLog.OPENALEX,
            fetch_type=fetch_type,
            status=PaperFetchLog.PENDING,
            started_date=start_date,
            fetch_since_date=date_to_fetch_from,
            next_cursor=next_cursor,
        )
        paper_fetch_log_id = lg.id
        sentry.log_info(f"Starting New OpenAlex pull: {paper_fetch_log_id}")
    else:
        # if paper_fetch_log_id is provided, it means we're retrying
        # so we should get the last fetch date from the log
        try:
            last_successful_run_log = PaperFetchLog.objects.get(id=paper_fetch_log_id)
            date_to_fetch_from = last_successful_run_log.fetch_since_date
            total_papers_processed = last_successful_run_log.total_papers_processed or 0
        except Exception as e:
            sentry.log_error(
                e, message=f"Failed to get last log for id {paper_fetch_log_id}"
            )
            # consider this a failed run
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                status=PaperFetchLog.FAILED,
                completed_date=timezone.now(),
            )
            return False

        sentry.log_info(f"Retrying OpenAlex pull: {paper_fetch_log_id}")

    try:
        open_alex = OpenAlex()

        while True:
            if fetch_type == PaperFetchLog.FETCH_NEW:
                works, next_cursor = open_alex.get_works(
                    types=["article"],
                    since_date=date_to_fetch_from,
                    next_cursor=next_cursor,
                )
            elif fetch_type == PaperFetchLog.FETCH_UPDATE:
                works, next_cursor = open_alex.get_works(
                    types=["article"],
                    from_updated_date=date_to_fetch_from,
                    next_cursor=next_cursor,
                )

            # if we've reached the end of the results, exit the loop
            if next_cursor is None or works is None or len(works) == 0:
                break

            process_openalex_works(works)

            total_papers_processed += len(works)

            # Update the log with the current state of the run
            if paper_fetch_log_id is not None:
                PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                    total_papers_processed=total_papers_processed,
                    next_cursor=next_cursor,
                )

        # done processing all works
        if paper_fetch_log_id is not None:
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                status=PaperFetchLog.SUCCESS,
                completed_date=timezone.now(),
                total_papers_processed=total_papers_processed,
                next_cursor=None,
            )
    except Exception as e:
        sentry.log_error(e, message="Failed to pull new works from OpenAlex, retrying")
        # update total_papers_processed in the log
        if paper_fetch_log_id is not None:
            PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                total_papers_processed=total_papers_processed,
            )
        try:
            self.retry(
                args=[retry + 1, paper_fetch_log_id],
                exc=e,
                countdown=10 + (retry * 2),
            )
        except MaxRetriesExceededError:
            # We've exhausted all retries, update the log to FAILED
            if paper_fetch_log_id is not None:
                PaperFetchLog.objects.filter(id=paper_fetch_log_id).update(
                    status=PaperFetchLog.FAILED,
                    completed_date=timezone.now(),
                )
            # Re-raise the original exception
            raise e

    return True


@app.task(queue=QUEUE_PULL_PAPERS)
def pull_openalex_author_works_batch(
    openalex_ids, user_id_to_notify_after_completion=None
):
    from notification.models import Notification
    from reputation.tasks import find_bounties_for_user_and_notify
    from user.related_models.user_model import User

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
        except Exception as e:
            sentry.log_error(e)

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

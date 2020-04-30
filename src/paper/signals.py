from django.db.models import Avg, IntegerField
from django.db.models.signals import post_save
from django.db.models.functions import Extract
from django.dispatch import receiver

from .models import Paper, Vote


@receiver(post_save, sender=Vote, dispatch_uid='recalculate_paper_votes')
def recalc_paper_votes(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    paper = instance.paper
    new_score = paper.calculate_score()

    if new_score > 0:
        ALGO_START_UNIX = 1588199677
        vote_avg_epoch = paper.votes.aggregate(avg=Avg(Extract('created_date', 'epoch'), output_field=IntegerField()))['avg']
        avg_hours_since_algo_start = (vote_avg_epoch - ALGO_START_UNIX) / 3600
        hot_score = avg_hours_since_algo_start + new_score + paper.discussion_count * 2

        paper.vote_avg_epoch = hot_score
    else:
        paper.vote_avg_epoch = 0

    paper.score = new_score
    paper.save()


@receiver(post_save, sender=Paper, dispatch_uid='pdf_extract_figures')
def queue_extract_figures_from_pdf(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    file_updated = check_file_updated(update_fields, instance.file)
    if not created and file_updated and not instance.figures.all():
        instance.extract_pdf_preview(use_celery=True)
        instance.extract_figures(use_celery=True)


def check_file_updated(update_fields, file):
    if update_fields is not None and file:
        return 'file' in update_fields
    return False

"""
Calculate rep for a given author.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand
from django.db import transaction

from paper.models import Paper
from reputation.models import AlgorithmVariables, Score, ScoreChange
from researchhub_comment.models import RhCommentThreadModel
from user.models import User


def calculate_user_score(user_id, algorithm_version, recalculate=False):
    user = User.objects.get(id=user_id)
    try:
        author = user.author_profile
    except ObjectDoesNotExist:
        return "User does not have an author profile."

    if not recalculate and is_already_calculated(author, algorithm_version):
        return "Reputation already calculated for this user and algorithm version. To recalculate, set the --recalculate flag to True."

    score_version = Score.get_version(author)
    calculate_author_score_hubs_citations(author, algorithm_version, score_version)
    calculate_author_score_hubs_paper_votes(user, algorithm_version, score_version)
    calculate_author_score_hubs_comments(user, algorithm_version, score_version)


def is_already_calculated(author, algo_version):
    try:
        score = Score.objects.filter(author=author).latest("created_date")
    except Score.DoesNotExist:
        return False

    try:
        ScoreChange.objects.filter(score=score, algorithm_version=algo_version).latest(
            "created_date"
        )
    except ScoreChange.DoesNotExist:
        return False

    return True


def calculate_author_score_hubs_paper_votes(user, algorithm_version, score_version):
    author = user.author_profile

    authored_papers = author.authored_papers.all()
    with transaction.atomic():
        for paper in authored_papers:
            votes = paper.votes.filter(vote_type__in=[1, 2])
            if votes.count() == 0:
                continue

            hubs = paper.hubs.filter(is_used_for_rep=True)
            for hub in hubs:
                for vote in votes:
                    if vote.vote_type == 1:
                        vote_value = 1
                    elif vote.vote_type == 2:
                        vote_value = -1

                    Score.update_score(
                        author,
                        hub,
                        algorithm_version,
                        score_version,
                        vote_value,
                        "votes",
                        vote.id,
                    )


def calculate_author_score_hubs_comments(user, algorithm_version, score_version):
    author = user.author_profile

    threads = RhCommentThreadModel.objects.filter(
        content_type=ContentType.objects.get(model="paper"),
        created_by=user,
    )

    for thread in threads:
        comments = thread.rh_comments.all()
        for comment in comments:
            paper = Paper.objects.get(id=comment.thread.object_id)
            votes = comment.votes.filter(vote_type__in=[1, 2])
            if votes.count() == 0:
                continue

            hubs = paper.hubs.filter(is_used_for_rep=True)
            for hub in hubs:
                for vote in votes:
                    if vote.vote_type == 1:
                        vote_value = 1
                    elif vote.vote_type == 2:
                        vote_value = -1

                    Score.update_score(
                        author,
                        hub,
                        algorithm_version,
                        score_version,
                        vote_value,
                        "votes",
                        vote.id,
                    )


def calculate_author_score_hubs_citations(author, algorithm_version, score_version):
    authored_papers = author.authored_papers.all()
    for paper in authored_papers:
        historical_papers = paper.history.all().order_by("history_date")
        if len(historical_papers) == 0:
            historical_papers = [paper]

        hubs = paper.hubs.filter(is_used_for_rep=True)
        for i, historical_paper in enumerate(historical_papers):
            previous_historical_paper = None
            if i != 0:
                previous_historical_paper = historical_papers[i - 1]

            citation_change = paper_citation_change(
                historical_paper, previous_historical_paper
            )

            if citation_change == 0:
                # If citation count hasn't changed, continue to the next paper history entry.
                continue

            for hub in hubs:
                Score.update_score(
                    author,
                    hub,
                    algorithm_version,
                    score_version,
                    citation_change,
                    "citations",
                    paper.id,
                )


def paper_citation_change(paper, previous_paper):
    previous_paper_citations = 0
    if previous_paper is not None:
        previous_paper_citations = previous_paper.citations

    return paper.citations - previous_paper_citations


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "version",
            type=int,
            help="Version of the algorithm to use",
        )
        parser.add_argument(
            "--recalculate",
            type=bool,
            help="Recalculate reputation for this user/algo_version combination",
            default=False,
        )

    def handle(self, *args, **options):
        for user in User.objects.iterator():
            calculate_user_score(user.id, options["version"], options["recalculate"])

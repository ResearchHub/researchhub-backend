"""
Calculate rep for a given author.
"""

import json

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db.models import Sum

from paper.models import Paper
from reputation.models import AlgorithmVariables, Score, ScoreChange
from user.models import User


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "user_id",
            type=int,
            help="ID of the user for whom to calculate reputation",
        )
        parser.add_argument(
            "version",
            type=int,
            help="Version of the algorithm to use",
        )

    def handle(self, *args, **options):
        user_id = options["user_id"]
        algorithm_version = options["version"]
        user = User.objects.get(id=user_id)
        author = user.author_profile
        self.calculate_author_score_hubs_citations(author, algorithm_version)

    def calculate_author_score_hubs_citations(self, author, algorithm_version):
        score_version = 1
        try:
            score = Score.objects.filter(author=author).latest("created_date")
        except Score.DoesNotExist:
            score = None

        if score:
            score_version = score.version + 1

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

                citation_change = self.paper_citation_change(
                    historical_paper, previous_historical_paper
                )

                if citation_change == 0:
                    # If citation count hasn't changed, continue to the next paper history entry.
                    continue

                for hub in hubs:
                    algorithm_variables = AlgorithmVariables.objects.filter(
                        hub=hub
                    ).latest("created_date")
                    try:
                        score = Score.objects.get(author=author, hub=hub)
                        if score.version != score_version:
                            score.version = score_version
                            score.score = 0
                            score.save()
                    except Score.DoesNotExist:
                        score = Score(
                            author=author,
                            hub=hub,
                            version=1,
                            score=0,
                        )
                        score.save()

                    try:
                        previous_score_change = ScoreChange.objects.filter(
                            score=score, score_version=score_version
                        ).latest("created_date")
                    except ScoreChange.DoesNotExist:
                        previous_score_change = None

                    previous_total_citation_count = 0
                    previous_variable_counts = {
                        "citations": 0,
                    }
                    if previous_score_change:
                        previous_total_citation_count = (
                            previous_score_change.variable_counts["citations"]
                        )
                        previous_variable_counts = previous_score_change.variable_counts

                    total_citation_count = (
                        previous_total_citation_count + citation_change
                    )

                    prev_rep = self.calculate_score_v1(
                        previous_total_citation_count,
                        algorithm_variables.variables["citations"]["bins"],
                    )
                    current_rep = self.calculate_score_v1(
                        previous_total_citation_count + citation_change,
                        algorithm_variables.variables["citations"]["bins"],
                    )

                    # Calculate the change in reputation
                    rep_change = current_rep - prev_rep

                    current_variable_counts = previous_variable_counts
                    current_variable_counts["citations"] = total_citation_count

                    score_change = ScoreChange(
                        algorithm_version=algorithm_version,
                        algorithm_variables=algorithm_variables,
                        score_after_change=current_rep,
                        score_change=rep_change,
                        raw_value_change=citation_change,
                        changed_content_type=ContentType.objects.get_for_model(Paper),
                        changed_object_id=paper.id,
                        changed_object_field="citations",
                        variable_counts=current_variable_counts,
                        score=score,
                        score_version=score_version,
                    )
                    score_change.save()

                    score.score = current_rep
                    score.save()

    def calculate_score_v1(self, citation_count, bins):
        rep = 0
        for key, val in bins.items():
            key_tuple = json.loads(key)

            citation_count_curr_bin = max(
                min(citation_count, key_tuple[1]) - key_tuple[0], 0
            )  # Take min of the citation count and the upper bound of the bin range then subtract the lower bound of the bin range and avoid going negative.
            rep += citation_count_curr_bin * val

        return rep

    def paper_citation_change(self, paper, previous_paper):
        previous_paper_citations = 0
        if previous_paper is not None:
            previous_paper_citations = previous_paper.citations

        return paper.citations - previous_paper_citations

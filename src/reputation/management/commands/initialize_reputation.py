"""
Calculate rep for a given author.
"""

from django.core.management.base import BaseCommand
from django.db.models import Sum

from reputation.models import AlgorithmVariables, Score, ScoreChange
from user.models import Author


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "author_id",
            type=int,
            help="ID of the author for whom to calculate reputation",
        )

    def handle(self, *args, **options):
        author_id = options["author_id"]
        author = Author.objects.get(id=author_id)
        authored_papers = author.authored_papers.all()
        for paper in authored_papers:
            historical_papers = paper.histories.all()
            if len(historical_papers) != 0:
                hubs = paper.hubs.filter(is_used_for_rep=True)
                for i, history in enumerate(historical_papers):
                    # Add an entry for each update to the paper's citation count.
                    previous_paper_citation_count = 0
                    if i != 0:
                        previous_paper_citation_count = historical_papers[
                            i - 1
                        ].citations

                    if previous_paper_citation_count == history.citations:
                        # If citation count hasn't changed, continue to the next paper history entry.
                        continue

                    for hub in hubs:
                        algorithm_variables = AlgorithmVariables.objects.filter(
                            hub=hub
                        ).latest()
                        score = Score.objects.get(author=author, hub_id=hub.id)
                        if not score:
                            score = Score(
                                author=author,
                                hub_id=hub.id,
                                score=0,
                            )
                            score.save()

                        previous_score_change = ScoreChange.objects.filter(
                            score=score
                        ).latest()

                        previous_total_citation_count = 0
                        previous_variable_counts = {
                            "total_citations": 0,
                            "citations": {},
                        }
                        if previous_score_change:
                            previous_total_citation_count = (
                                previous_score_change.variable_counts["citations"]
                            )
                            previous_variable_counts = (
                                previous_score_change.variable_counts
                            )

                        paper_citation_change = (
                            history.citations - previous_paper_citation_count
                        )

                        total_citation_count = (
                            previous_total_citation_count + paper_citation_change
                        )

                        prev_rep = self.calculate_score_v1(
                            previous_total_citation_count,
                            algorithm_variables.variables["citations"]["bins"],
                        )

                        current_rep = self.calculate_score_v1(
                            previous_total_citation_count + paper_citation_change,
                            algorithm_variables.variables["citations"]["bins"],
                        )

                        rep_change = current_rep - prev_rep

                        current_variable_counts = previous_variable_counts
                        current_variable_counts[
                            "total_citations"
                        ] = total_citation_count
                        current_variable_counts["citations"][
                            paper.id
                        ] = history.citations

                        score_change = ScoreChange(
                            algorithm_version=1,
                            algorithm_variables=algorithm_variables,
                            score_after_change=current_rep,
                            score_change=rep_change,
                            raw_value_change=paper_citation_change,
                            changed_content_type=ContentType.objects.get_for_model(
                                Paper
                            ),
                            changed_object_id=paper.id,
                            changed_object_field="citations",
                            variable_counts=current_variable_counts,
                            score=score,
                        )
                        score_change.save()

                        score.score = current_rep
                        score.save()

    def calculate_score_v1(citation_count, bins):
        rep = 0
        for key, val in bins.items():
            citation_count_curr_bin = max(
                min(citation_count, key[1]) - key[0], 0
            )  # Take min of the citation count and the upper bound of the bin range then subtract the lower bound of the bin range and avoid going negative.
            rep += citation_count_curr_bin * val

        return rep

import json
import math

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import JSONField

from discussion.reaction_models import Vote
from paper.related_models.citation_model import Citation
from utils.models import DefaultModel

ALGORITHM_VERSION = 1


class Score(DefaultModel):
    author = models.ForeignKey("user.Author", on_delete=models.CASCADE, db_index=True)
    hub = models.ForeignKey("hub.Hub", on_delete=models.CASCADE, db_index=True)
    score = models.IntegerField(default=0)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (
            "author",
            "hub",
        )

    # FIXME query score algorithm variables for bins.
    @property
    def percentile(self):
        if self.score <= 1000:
            return 0.25 * (self.score / 1000)
        elif self.score <= 10000:
            return 0.25 + 0.25 * ((self.score - 1000) / 9000)
        elif self.score <= 100000:
            return 0.5 + 0.25 * ((self.score - 10000) / 90000)
        else:
            return 0.75 + 0.25 * ((self.score - 100000) / 900000)

    @classmethod
    def get_scores(cls, author):
        return cls.objects.filter(author=author)

    @classmethod
    def get_max_score(cls, author):
        return cls.objects.filter(author=author).order_by("-score").first()

    @classmethod
    def get_or_create_score(cls, author, hub):
        try:
            score = cls.objects.get(author=author, hub=hub)
        except cls.DoesNotExist:
            score = cls(
                author=author,
                hub=hub,
                score=0,
            )
            score.save()

        cls.objects.select_for_update().get(id=score.id)

        return score

    @classmethod
    def reset_scores(cls, author):
        scores = Score.get_scores(author)
        for score in scores:
            algorithm_variables = AlgorithmVariables.objects.filter(
                hub=score.hub
            ).latest("created_date")
            score.score = 0
            score.save()
            ScoreChange.objects.filter(
                score=score,
                algorithm_version=ALGORITHM_VERSION,
                algorithm_variables=algorithm_variables,
            ).delete()

    @classmethod
    def update_score_vote(cls, author, hub, vote):
        content_type = ContentType.objects.get_for_model(Vote)
        score = cls.get_or_create_score(author, hub)
        previous_score_change = (
            ScoreChange.objects.filter(
                score=score,
                changed_object_id=vote.id,
                changed_content_type=content_type,
            )
            .order_by("created_date")
            .last()
        )
        vote_value = ScoreChange.vote_change(vote, previous_score_change)
        if vote_value == 0:
            return

        score = cls.get_or_create_score(author, hub)

        score_change = ScoreChange.create_score_change_votes(
            score,
            vote_value,
            content_type,
            vote.id,
        )

        score.score = score_change.score_after_change
        score.save()

        return score

    @classmethod
    def update_score_citations(
        cls,
        author,
        hub,
        citation_change,
        citation_id,
        paper_work_type,
    ):
        content_type = ContentType.objects.get_for_model(Citation)

        try:
            algorithm_variables = AlgorithmVariables.objects.filter(hub=hub).latest(
                "created_date"
            )
            score = cls.objects.select_for_update().get(
                hub=hub,
                author=author,
            )
            previous_score_change_object = ScoreChange.get_latest_score_change_object(
                score,
                citation_id,
                content_type,
                algorithm_variables,
            )
        except (Score.DoesNotExist, ScoreChange.DoesNotExist):
            previous_score_change_object = None

        if previous_score_change_object:
            return

        score = cls.get_or_create_score(author, hub)

        score_change = ScoreChange.create_score_change_citations(
            score,
            citation_change,
            content_type,
            citation_id,
            paper_work_type,
        )

        score.score = score_change.score_after_change
        score.save()

        return score


class ScoreChange(DefaultModel):
    algorithm_version = models.IntegerField(default=1)
    algorithm_variables = models.ForeignKey(
        "reputation.AlgorithmVariables", on_delete=models.CASCADE
    )
    score_after_change = models.IntegerField()
    score_change = models.IntegerField()
    raw_value_change = models.IntegerField()  # change of number of citations or votes.
    changed_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE
    )  # content type of paper, historical paper or vote.
    changed_object_id = (
        models.PositiveIntegerField()
    )  # id of the paper (with updated citation) or vote.
    changed_object_field = models.CharField(
        max_length=100
    )  # field name of the changed object, citation, upvote.
    variable_counts = JSONField(default=dict)
    # {
    #     "citations": 10,
    #     "votes": 5,
    # }
    score = models.ForeignKey(
        "reputation.Score", on_delete=models.CASCADE, db_index=True
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)

    @classmethod
    def get_latest_score_change(cls, score, algorithm_variables=None):
        if algorithm_variables is None:
            algorithm_variables = AlgorithmVariables.objects.filter(
                hub=score.hub
            ).latest("created_date")
        try:
            previous_score_change = cls.objects.filter(
                score=score,
                algorithm_version=ALGORITHM_VERSION,
                algorithm_variables=algorithm_variables,
            ).latest("created_date")
        except cls.DoesNotExist:
            previous_score_change = None

        return previous_score_change

    @classmethod
    def get_latest_score_change_object(
        cls, score, object_id, content_type, algorithm_variables=None
    ):
        if algorithm_variables is None:
            algorithm_variables = AlgorithmVariables.objects.filter(
                hub=score.hub
            ).latest("created_date")

        return (
            ScoreChange.objects.filter(
                score=score,
                changed_object_id=object_id,
                changed_content_type=content_type,
                algorithm_variables=algorithm_variables,
            )
            .order_by("created_date")
            .last()
        )

    @classmethod
    def create_score_change_citations(
        cls,
        score,
        raw_value_change,
        content_type,
        object_id,
        paper_work_type,
    ):
        algorithm_variables = AlgorithmVariables.objects.filter(hub=score.hub).latest(
            "created_date"
        )
        previous_score_change = cls.get_latest_score_change(score, algorithm_variables)

        previous_score = 0
        previous_variable_counts = {
            "citations": 0,
            "votes": 0,
        }
        if previous_score_change:
            previous_score = previous_score_change.score_after_change
            previous_variable_counts = previous_score_change.variable_counts

        current_variable_counts = previous_variable_counts
        current_variable_counts["citations"] = (
            current_variable_counts["citations"] + raw_value_change
        )

        score_value_change = cls.calculate_score_change_citations(
            score, algorithm_variables, raw_value_change, paper_work_type
        )

        current_rep = previous_score + score_value_change

        score_change = cls(
            algorithm_version=ALGORITHM_VERSION,
            algorithm_variables=algorithm_variables,
            score_after_change=current_rep,
            score_change=score_value_change,
            raw_value_change=raw_value_change,
            changed_content_type=content_type,
            changed_object_id=object_id,
            changed_object_field="citations",
            variable_counts=current_variable_counts,
            score=score,
        )
        score_change.save()

        return score_change

    @classmethod
    def create_score_change_votes(
        cls,
        score,
        raw_value_change,
        content_type,
        object_id,
    ):
        algorithm_variables = AlgorithmVariables.objects.filter(hub=score.hub).latest(
            "created_date"
        )
        previous_score_change = cls.get_latest_score_change(score, algorithm_variables)

        previous_score = 0
        previous_variable_counts = {
            "citations": 0,
            "votes": 0,
        }
        if previous_score_change:
            previous_score = previous_score_change.score_after_change
            previous_variable_counts = previous_score_change.variable_counts

        current_variable_counts = previous_variable_counts
        current_variable_counts["votes"] = (
            current_variable_counts["votes"] + raw_value_change
        )

        score_value_change = cls.calculate_score_change_votes(
            score,
            algorithm_variables,
            raw_value_change,
        )

        current_rep = previous_score + score_value_change

        score_change = cls(
            algorithm_version=ALGORITHM_VERSION,
            algorithm_variables=algorithm_variables,
            score_after_change=current_rep,
            score_change=score_value_change,
            raw_value_change=raw_value_change,
            changed_content_type=content_type,
            changed_object_id=object_id,
            changed_object_field="vote_type",
            variable_counts=current_variable_counts,
            score=score,
        )
        score_change.save()

        return score_change

    @classmethod
    def calculate_score_change_citations(
        cls,
        score,
        algorithm_variables,
        raw_value_change,
        paper_work_type,
    ):
        previous_score_change = cls.get_latest_score_change(score, algorithm_variables)

        previous_total_count = 0

        if previous_score_change:
            previous_total_count = previous_score_change.variable_counts["citations"]

        prev_rep = 0
        current_rep = 0

        prev_rep = cls.calculate_citation_score_v2(
            previous_total_count,
            algorithm_variables.variables["citations"]["bins"],
            paper_work_type,
        )
        current_rep = cls.calculate_citation_score_v2(
            previous_total_count + raw_value_change,
            algorithm_variables.variables["citations"]["bins"],
            paper_work_type,
        )

        return current_rep - prev_rep

    @classmethod
    def calculate_score_change_votes(
        cls,
        score,
        algorithm_variables,
        raw_value_change,
    ):
        previous_score_change = cls.get_latest_score_change(score, algorithm_variables)

        previous_total_count = 0

        if previous_score_change:
            previous_total_count = previous_score_change.variable_counts["votes"]

        prev_rep = 0
        current_rep = 0

        prev_rep = previous_total_count
        current_rep = previous_total_count + raw_value_change

        return current_rep - prev_rep

    def calculate_citation_score_v1(citation_count, bins):
        rep = 0
        for key, val in bins.items():
            key_tuple = json.loads(key)

            citation_count_curr_bin = max(
                min(citation_count, key_tuple[1]) - key_tuple[0], 0
            )  # Take min of the citation count and the upper bound of the bin range then subtract the lower bound of the bin range and avoid going negative.
            rep += citation_count_curr_bin * val

        return rep

    def calculate_citation_score_v2(citation_count, bins, paper_work_type):
        rep = 0
        for key, val in bins.items():
            key_tuple = json.loads(key)

            citation_count_curr_bin = max(
                min(citation_count, key_tuple[1]) - key_tuple[0], 0
            )  # Take min of the citation count and the upper bound of the bin range then subtract the lower bound of the bin range and avoid going negative.
            rep_change = citation_count_curr_bin * val
            if paper_work_type == "review":
                rep_change = math.ceil(rep_change / 5)

            rep += rep_change

        return rep

    def vote_change(vote, previous_score_change):
        vote_values = {
            Vote.UPVOTE: 1,
            Vote.DOWNVOTE: -1,
            Vote.NEUTRAL: 0,
        }

        vote_value = vote_values[vote.vote_type]
        previous_vote_value = 0
        if previous_score_change:
            previous_vote_value = previous_score_change.raw_value_change

        return vote_value - previous_vote_value


# AlgorithmVariables stores the variables required to calculate the reputation score.
# Currently each upvote is worth 1 point.
class AlgorithmVariables(DefaultModel):
    # {"citations":
    #   {"bins":{(0, 2): 50, (2, 12): 100, (12, 200): 250, (200, 2800): 100}},
    #  "votes": {"value": 1},
    #  "bins": [[0, 1000], [1_000, 10_000], [10_000, 100_000], [100_000, 1_000_000]]
    # }
    variables = JSONField()
    hub = models.ForeignKey("hub.Hub", on_delete=models.CASCADE, db_index=True)
    created_date = models.DateTimeField(auto_now_add=True)

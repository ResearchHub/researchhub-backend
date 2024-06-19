from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import JSONField

from utils.models import DefaultModel


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
    )  # content type of citation or vote.
    changed_object_id = (
        models.PositiveIntegerField()
    )  # id of the paper (with updated citation) or vote.
    changed_object_field = models.CharField(
        max_length=100
    )  # field name of the changed object, citation, upvote.
    variable_counts = JSONField(default=dict)
    # {
    #     "total_citations": 10,
    #     "total_votes": 5,
    #     "citations": {
    #         "id_1": 2,
    #         "id_2": 5,
    #         "id_3": 3,
    #     },
    #     "votes": {
    #         "id_1": 4,
    #         "id_2": 1,
    #     },
    # }
    score = models.ForeignKey(
        "reputation.Score", on_delete=models.CASCADE, db_index=True
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)


# AlgorithmVariables stores the variables required to calculate the reputation score.
# Currently each upvote is worth 1 point.
class AlgorithmVariables(DefaultModel):
    # {"citations":
    #   {"bins":{(0, 2): 50, (2, 12): 100, (12, 200): 250, (200, 2800): 100}},
    #  "votes": {"value": 1},
    #  "bins": [1000, 10_000, 100_000, 1_000_000]
    # }
    variables = JSONField()
    hub = models.ForeignKey("hub.Hub", on_delete=models.CASCADE, db_index=True)
    created_date = models.DateTimeField(auto_now_add=True)

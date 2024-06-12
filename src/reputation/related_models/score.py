from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import JSONField
from django.db import models

from utils.models import DefaultModel


class Score(DefaultModel):
    author = models.ForeignKey("author.Author", on_delete=models.CASCADE, db_index=True)
    hub = models.ForeignKey("hub.Hub", on_delete=models.CASCADE, db_index=True)
    score = models.IntegerField(default=0)
    algorithm_version = models.IntegerField(default=1)
    algorithm_variables = models.ForeignKey(
        "reputation.AlgorithmVariables", on_delete=models.CASCADE
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (
            "author",
            "hub",
            "algorithm_version",
            "algorithm_variables",
        )
        indexes = [
            models.Index(
                fields=["author", "hub"],
            ),
        ]


class ScoreChange(DefaultModel):
    score_change = models.IntegerField()
    raw_value_change = (
        models.IntegerField()
    )  # change of number of citations or upvotes.
    changed_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE
    )  # content type of citation or upvote.
    changed_object_id = (
        models.PositiveIntegerField()
    )  # id of the paper (with updated citation) or discussion vote.
    changed_object_field = models.CharField(
        max_length=100
    )  # field name of the changed object, citation, upvote.
    variable_counts = JSONField(default=dict)  # {"citations": 10, "votes": 5}
    reputation = models.ForeignKey(
        "reputation.Reputation", on_delete=models.CASCADE, db_index=True
    )
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)


# AlgorithmVariables stores the variables required to calculate the reputation score.
# Currently each upvote is worth 1 point.
class AlgorithmVariables(DefaultModel):
    # {"citations":
    #   {"bins":{(0, 2): 50, (2, 12): 100, (12, 200): 250, (200, 2800): 100}}
    #  "votes": {"value": 1}}
    variables = JSONField()
    hub = models.ForeignKey("hub.Hub", on_delete=models.CASCADE, db_index=True)
    created_date = models.DateTimeField(auto_now_add=True)

import math
from time import time

from django.db import models
from django.db.models import JSONField

from reputation.distributions import create_paper_reward_distribution

OPEN_ACCESS_MULTIPLIER = 1.0
OPEN_DATA_MULTIPLIER = 3.0
PREREGISTERED_MULTIPLIER = 2.0


class HubCitationValue(models.Model):
    hub = models.ForeignKey("hub.Hub", on_delete=models.CASCADE, db_index=True)
    # {"citations":
    #   {"bins":{(0, 2): {"slope": 0.29, "intercept": 10}, (2, 12): {"slope": 0.35, "intercept": 100}, (12, 200): {"slope": 0.40, "intercept": 200}, (200, 2800): {"slope": 0.53, "intercept": 300}}},
    # }
    variables = JSONField(null=True, blank=True, default=None)

    created_date = models.DateTimeField(auto_now_add=True)

    @classmethod
    def calculate_rsc_reward(
        cls, paper, citation_change, is_open_data, is_preregistered
    ):
        hub = paper.unified_document.get_primary_hub()
        hub_citation_value = cls.objects.filter(hub=hub).order_by("created_date").last()
        return hub_citation_value.rsc_reward_algo(
            citation_change, is_open_data, is_preregistered
        )

    def rsc_reward_algo(self, citation_change, is_open_data, is_preregistered):
        hub_citation_variables = None
        for bin_range, bin_value in self.variables["citations"]["bins"].items():
            bin_range = eval(bin_range)
            bin_value = eval(bin_value)
            if bin_range[0] <= citation_change <= bin_range[1]:
                hub_citation_variables = bin_value
                break

        rsc_reward_with_multipliers = 10 ** (
            math.log(citation_change, 10) * hub_citation_variables["slope"]
            + hub_citation_variables["intercept"]
        )

        rsc_reward = rsc_reward_with_multipliers
        base_rsc_reward = rsc_reward_with_multipliers / (
            OPEN_ACCESS_MULTIPLIER * OPEN_DATA_MULTIPLIER * PREREGISTERED_MULTIPLIER
        )

        if not is_open_data:
            rsc_reward -= base_rsc_reward * OPEN_DATA_MULTIPLIER

        if not is_preregistered:
            rsc_reward -= base_rsc_reward * PREREGISTERED_MULTIPLIER

        return rsc_reward

    # This method is used to calculate the base reward for the initial paper claim.
    @classmethod
    def calculate_base_claim_rsc_reward(cls, paper):
        return cls.calculate_rsc_reward(paper, paper.citations, False, False)


class PaperReward(models.Model):
    paper = models.ForeignKey("paper.Paper", on_delete=models.CASCADE, db_index=True)
    author = models.ForeignKey("user.Author", on_delete=models.CASCADE, db_index=True)
    citation_change = models.PositiveIntegerField()
    citation_count = models.PositiveIntegerField()
    rsc_value = models.FloatField()
    is_open_data = models.BooleanField(default=False)
    is_preregistered = models.BooleanField(default=False)
    distribution = models.ForeignKey(
        "reputation.Distribution",
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    @classmethod
    def claim_paper_rewards(cls, paper, author, is_open_data, is_preregistered):
        rsc_value = HubCitationValue.calculate_rsc_reward(
            paper, paper.citations, is_open_data, is_preregistered
        )
        paper_reward = cls.objects.create(
            paper=paper,
            author=author,
            citation_change=paper.citations,
            citation_count=paper.citations,
            rsc_value=rsc_value,
            is_open_data=is_open_data,
            is_preregistered=is_preregistered,
        )

        return paper_reward

    @classmethod
    def distribute_paper_rewards(cls, paper, author):
        from reputation.distributor import Distributor

        try:
            paper_reward = cls.objects.get(
                paper=paper, author=author, distribution=None
            )
        except cls.DoesNotExist:
            raise Exception("There is no unpaid reward for this paper")

        distribution = create_paper_reward_distribution(paper_reward.rsc_value)
        distributor = Distributor(distribution, author.user, paper_reward, time())
        distribution = distributor.distribute()

        paper_reward.distribution = distribution
        paper_reward.save()

        return paper_reward

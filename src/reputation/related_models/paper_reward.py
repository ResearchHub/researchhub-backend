import math
from time import time

from django.db import models
from django.db.models import JSONField

from reputation.distributions import create_paper_reward_distribution


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
        hub_citation_variables = None
        for bin_range, bin_value in hub_citation_value.variables["citations"][
            "bins"
        ].items():
            bin_range = eval(bin_range)
            print("bin_range", bin_range)
            print("citation_change", citation_change)
            if bin_range[0] <= citation_change < bin_range[1]:
                hub_citation_variables = bin_value
                break

        rsc_reward = 10 ** (
            math.log(citation_change, 10) * hub_citation_variables["slope"]
            + hub_citation_variables["intercept"]
        )

        rsc_reward_with_multipliers = rsc_reward

        if is_open_data:
            rsc_reward_with_multipliers += rsc_reward * 3.0

        if is_preregistered:
            rsc_reward_with_multipliers += rsc_reward * 2.0

        return rsc_reward_with_multipliers


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

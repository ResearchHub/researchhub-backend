from time import time

from django.db import models

from reputation.distributions import create_paper_reward_distribution


class HubCitationValue(models.Model):
    hub = models.ForeignKey("hub.Hub", on_delete=models.CASCADE, db_index=True)
    rsc_per_citation = models.FloatField()

    created_date = models.DateTimeField(auto_now_add=True)

    @classmethod
    def calculate_rsc_reward(cls, paper, citation_change):
        hub = paper.unified_document.get_primary_hub()
        hub_citation_value = cls.objects.get(hub=hub).rsc_per_citation
        rsc_reward = citation_change * hub_citation_value

        return rsc_reward


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
    )

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    @classmethod
    def claim_paper_rewards(cls, paper, author, is_open_data, is_preregistered):
        rsc_value = HubCitationValue.calculate_rsc_reward(paper, paper.citation)
        paper_reward = cls(
            paper=paper,
            author=author,
            citation_change=paper.citation,
            citation_count=paper.citation,
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
            return Exception("There is no unpaid reward for this paper")

        distribution = create_paper_reward_distribution(paper_reward.rsc_value)
        distributor = Distributor(distribution, author.user, paper_reward, time.time())
        distributor.distribute()

        paper_reward.distribution = distribution
        paper_reward.save()

        return paper_reward

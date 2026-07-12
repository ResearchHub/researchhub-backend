import logging

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models, transaction
from django.db.models import JSONField, Sum
from django.db.models.deletion import SET_NULL

from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from paper.utils import PAPER_SCORE_Q_ANNOTATION
from reputation.models import Score
from researchhub_comment.models import RhCommentThreadModel
from user.related_models.profile_image_storage import ProfileImageStorage
from user.related_models.school_model import University
from user.related_models.user_model import User

logger = logging.getLogger(__name__)


fs = ProfileImageStorage()


class Author(models.Model):
    SOURCE_OPENALEX = "OPENALEX"
    SOURCE_RESEARCHHUB = "RESEARCHHUB"
    SOURCE_CHOICES = [
        (SOURCE_OPENALEX, "OpenAlex"),
        (SOURCE_RESEARCHHUB, "ResearchHub"),
    ]
    user = models.OneToOneField(
        User,
        related_name="author_profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    first_name = models.CharField(max_length=150)  # Same max_length as User
    last_name = models.CharField(max_length=150)  # Same max_length as User
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    description = models.TextField(null=True, blank=True)
    h_index = models.IntegerField(default=0)
    i10_index = models.IntegerField(default=0)
    profile_image = models.FileField(
        upload_to="uploads/author_profile_images/%Y/%m/%d",
        max_length=2048,
        default=None,
        null=True,
        blank=True,
        storage=fs,
    )
    author_score = models.IntegerField(default=0)
    university = models.ForeignKey(
        University, on_delete=models.SET_NULL, null=True, blank=True
    )
    orcid_id = models.TextField(default=None, null=True, blank=True)
    openalex_ids = ArrayField(
        models.CharField(
            max_length=64, default=None, null=True, blank=True, unique=True
        ),
        null=False,
        default=list,
    )
    education = ArrayField(
        JSONField(blank=True, null=True), default=list, blank=True, null=True
    )
    headline = models.TextField(blank=True, null=True)
    facebook = models.URLField(max_length=255, default=None, null=True, blank=True)
    twitter = models.URLField(max_length=255, default=None, null=True, blank=True)
    linkedin = models.URLField(max_length=255, default=None, null=True, blank=True)
    google_scholar = models.URLField(
        max_length=255, default=None, null=True, blank=True
    )
    claimed = models.BooleanField(default=True, null=True, blank=True)
    country_code = models.CharField(
        blank=True,
        null=True,
        max_length=20,
    )

    # Indicates whether the user was created through the RH platform or through another
    # source such as OpenAlex
    created_source = models.CharField(
        max_length=20,
        null=False,
        blank=False,
        choices=SOURCE_CHOICES,
        default=SOURCE_RESEARCHHUB,
    )

    # Indicates the last time we did a full fetch from OpenAlex which includes all the
    # works
    last_full_fetch_from_openalex = models.DateTimeField(null=True, blank=True)

    # AKA Impact Factor. Derived from OpenAlex:  https://en.wikipedia.org/wiki/Impact_factor
    two_year_mean_citedness = models.FloatField(default=0)

    # An author's profile can be merged with another author's
    merged_with_author = models.ForeignKey(
        "self",
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name="merged_authors",
    )

    class Meta:
        indexes = [
            GinIndex(fields=["openalex_ids"], name="user_author_openalex_ids_idx"),
        ]

    def __str__(self):
        university = self.university
        if university is None:
            university_name = ""
            university_city = ""
        else:
            university_name = university.name
            university_city = university.city
        return f"{self.first_name}_{self.last_name}_{university_name}_{university_city}"

    def build_headline(self):
        from collections import Counter

        if self.headline:
            return self.headline

        try:
            all_topics = []
            authored_papers = self.papers.all()

            for p in authored_papers:
                unified_document = p.unified_document
                all_topics += list(unified_document.topics.all())

            topic_counts = Counter(all_topics)

            # Sort topics by frequency
            sorted_topics = sorted(
                topic_counts.items(), key=lambda x: x[1], reverse=True
            )

            # Extract topics from sorted list
            sorted_topics = [topic for topic, _ in sorted_topics]

            if not sorted_topics:
                return None

            return "Author with expertise in " + sorted_topics[0].display_name
        except Exception:
            logger.exception("Failed to build headline for author id %s", self.id)
            return None

    @property
    def full_name(self):
        return self.first_name + " " + self.last_name

    @property
    def is_verified(self):
        """
        Check if the user account is verified.
        Returns `False` if the user was not successfully verified or
        if no verification record exists.
        """
        if self.user is None:
            return False

        return self.user.is_verified

    @property
    def is_orcid_connected(self):
        if not self.user:
            return False
        return SocialAccount.objects.filter(
            user=self.user, provider=OrcidProvider.id
        ).exists()

    @property
    def orcid_verified_edu_email(self):
        if not self.user:
            return None
        account = SocialAccount.objects.filter(
            user=self.user, provider=OrcidProvider.id
        ).first()
        if not account:
            return None
        emails = account.extra_data.get("verified_edu_emails", [])
        return emails[0] if emails else None

    def get_all_authorships(self):
        """
        Get all authorships for this author, including merged shadow authors.
        Uses UNION instead of OR for better query performance.
        """
        direct = Authorship.objects.filter(author=self)
        merged = Authorship.objects.filter(author__merged_with_author=self)
        return direct.union(merged)

    @property
    def open_access_pct(self):
        paper_ids = list(self.get_all_authorships().values_list("paper_id", flat=True))
        authored_papers = Paper.objects.filter(id__in=paper_ids)
        total_paper_count = authored_papers.count()

        if total_paper_count == 0:
            return 0
        return authored_papers.filter(is_open_access=True).count() / total_paper_count

    @property
    def citation_count(self):
        # UNION doesn't support aggregate(), so sum two indexed queries
        direct = (
            Authorship.objects.filter(author=self).aggregate(
                total=Sum("paper__citations")
            )["total"]
            or 0
        )
        merged = (
            Authorship.objects.filter(author__merged_with_author=self).aggregate(
                total=Sum("paper__citations")
            )["total"]
            or 0
        )
        return direct + merged

    @property
    def reputation_list(self):
        scores = (
            Score.objects.filter(author=self, score__gt=0)
            .select_related("hub")
            .order_by("-score")
        )

        reputation_list = [
            {
                "hub": {
                    "id": score.hub.id,
                    "name": score.hub.name,
                    "slug": score.hub.slug,
                },
                "score": score.score,
                "percentile": score.percentile,
                "bins": [
                    [0, 1000],
                    [1000, 10000],
                    [10000, 100000],
                    [100000, 1000000],
                ],  # FIXME: Replace with bins from algo vars table
            }
            for score in scores
        ]

        return reputation_list

    @property
    def paper_count(self):
        # Get paper IDs from both queries, combine in set for deduplication
        direct_ids = set(
            Authorship.objects.filter(author=self).values_list("paper_id", flat=True)
        )
        merged_ids = set(
            Authorship.objects.filter(author__merged_with_author=self).values_list(
                "paper_id", flat=True
            )
        )
        return len(direct_ids | merged_ids)

    @property
    def achievements(self):
        upvote_count = getattr(self.user, "upvote_count", 0)
        peer_review_count = getattr(self.user, "peer_review_count", 0)
        amount_funded = getattr(self.user, "amount_funded", 0)
        return {
            "CITED_AUTHOR": {
                "value": self.citation_count,
                "milestones": [10, 100, 1000],
            },
            "OPEN_ACCESS": {
                "value": self.open_access_pct,
                "milestones": [0.5, 0.75, 0.875],
            },
            "OPEN_SCIENCE_SUPPORTER": {
                "value": amount_funded,
                "milestones": [10, 1000, 10000],
            },
            "HIGHLY_UPVOTED": {
                "value": upvote_count,
                "milestones": [
                    10,
                    100,
                    1000,
                ],
            },
            "EXPERT_PEER_REVIEWER": {
                "value": peer_review_count,
                "milestones": [1, 25, 50],
            },
        }

    def calculate_score(self):
        aggregated_score = self.papers.annotate(
            paper_score=PAPER_SCORE_Q_ANNOTATION
        ).aggregate(total_score=Sum("paper_score"))
        aggregated_discussion_count = self.papers.aggregate(
            total_score=Sum("discussion_count")
        )
        paper_count = self.papers.count()
        paper_scores = 0
        if aggregated_score["total_score"]:
            paper_scores = aggregated_score["total_score"]

        if aggregated_discussion_count["total_score"]:
            paper_scores += 2 * aggregated_discussion_count["total_score"]

        return paper_scores + paper_count

    def calculate_hub_scores(self):
        with transaction.atomic():
            Score.reset_scores(self)
            self._calculate_score_hub_citations()
            self._calculate_score_hub_paper_votes()
            self._calculate_score_hub_comments()

    def _calculate_score_hub_paper_votes(self):
        authored_papers = Paper.objects.filter(
            authorships__author=self,
            work_type__in=["preprint", "article", "review"],
        ).only("id", "votes", "unified_document")

        for paper in authored_papers:
            votes = paper.votes.filter(vote_type__in=[1, 2])
            if votes.count() == 0:
                continue

            hub = paper.unified_document.get_primary_hub()
            if hub is None:
                logger.warning("Paper %s has no primary hub", paper.id)
                continue

            for vote in votes:
                Score.update_score_vote(self, hub, vote)

    def _calculate_score_hub_comments(self):
        threads = RhCommentThreadModel.objects.filter(
            content_type=ContentType.objects.get(model="paper"),
            created_by=self.user,
        ).only("rh_comments")

        paper_ids = [thread.object_id for thread in threads]
        papers = Paper.objects.filter(
            id__in=paper_ids, work_type__in=["preprint", "article", "review"]
        ).order_by("created_date")

        paper_dict = {paper.id: paper for paper in papers}

        for thread in threads:
            comments = thread.rh_comments.all()
            for comment in comments:
                paper = paper_dict.get(thread.object_id)
                if paper is None:
                    continue

                votes = comment.votes.filter(vote_type__in=[1, 2])
                if votes.count() == 0:
                    continue

                hub = paper.unified_document.get_primary_hub()
                if hub is None:
                    logger.warning("Paper %s has no primary hub", paper.id)
                    continue

                for vote in votes:
                    Score.update_score_vote(self, hub, vote)

    def _calculate_score_hub_citations(self):
        authorships = Authorship.objects.filter(author=self).select_related(
            "paper", "author"
        )

        for authorship in authorships:
            authorship.paper.update_scores_citations(authorship.author)

    def get_rep_score(self):
        score = Score.get_max_score(self)
        if score is None:
            return 0

        return score.score

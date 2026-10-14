import logging

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import JSONField
from django.db.models.deletion import SET_NULL

from user.related_models.profile_image_storage import ProfileImageStorage
from user.related_models.school_model import University
from user.related_models.user_model import User
from utils.models import SoftDeletableModel

logger = logging.getLogger(__name__)


fs = ProfileImageStorage()


class Author(SoftDeletableModel):
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

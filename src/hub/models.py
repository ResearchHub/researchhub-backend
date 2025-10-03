from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models import Q, Sum
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from researchhub_access_group.models import Permission

HELP_TEXT_IS_REMOVED = "Hides the hub because it is not allowed."


def get_default_hub_category():
    """Get or create a default value for the hub categories"""

    return HubCategory.objects.get_or_create(category_name="Other")[0]


class HubCategory(models.Model):
    """A grouping of hubs, organized by category"""

    def __str__(self):
        return self.category_name

    def __int__(self):
        return self.id

    category_name = models.CharField(max_length=1024, unique=True)


class Hub(models.Model):
    """A grouping of papers, organized by subject"""

    class Namespace(models.TextChoices):
        """
        Since hubs are used like tags, the namespace is used to differentiate
        between different types of hubs.
        """

        JOURNAL = "journal", _("Journal")

    UNLOCK_AFTER = 14

    name = models.CharField(max_length=1024, unique=False)
    description = models.TextField(default="")
    hub_image = models.FileField(
        max_length=1024,
        upload_to="uploads/hub_images/%Y/%m/%d",
        default=None,
        null=True,
        blank=True,
    )
    slug = models.CharField(max_length=256, unique=True, blank=True, null=True)
    slug_index = models.IntegerField(blank=True, null=True)
    acronym = models.CharField(max_length=255, default="", blank=True)
    is_locked = models.BooleanField(default=False)
    subscribers = models.ManyToManyField(
        "user.User", related_name="subscribed_hubs", through="HubMembership"
    )
    permissions = GenericRelation(
        Permission,
        help_text="A member of given hub that has special power. \
            Note this is different from HubMembership (subscribers)",
        related_name="hub",
        related_query_name="hub_source",
    )
    category = models.ForeignKey(
        HubCategory, on_delete=models.CASCADE, default=get_default_hub_category
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    subscriber_count = models.IntegerField(default=0)
    paper_count = models.IntegerField(default=0)
    discussion_count = models.IntegerField(default=0)

    is_removed = models.BooleanField(default=False, help_text=HELP_TEXT_IS_REMOVED)

    concept = models.OneToOneField(
        "tag.concept",
        related_name="hub",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    subfield = models.OneToOneField(
        "topic.subfield",
        related_name="hub",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    is_used_for_rep = models.BooleanField(default=False)

    namespace = models.TextField(
        choices=Namespace.choices,
        default=None,
        null=True,
    )

    class Meta:
        constraints = [
            # Original case-sensitive constraint
            # (keeps exact duplicates from being created)
            models.UniqueConstraint(
                fields=["name", "namespace"], name="unique_name_namespace"
            ),
            # Case-insensitive unique constraint to prevent duplicates
            # with different cases. Example: Prevents "Nature", "nature",
            # "NATURE" from coexisting with same namespace
            models.UniqueConstraint(
                # Field 1: UPPER(name) - case-insensitive (used for comparison)
                models.Func("name", function="UPPER"),
                # Field 2: namespace - as-is
                "namespace",
                # Constraint name in DB
                name="unique_name_namespace_case_insensitive",
            ),
        ]
        indexes = [
            models.Index(
                models.Func("name", function="UPPER"), name="hub_hub_name_upper_idx"
            )
        ]

    def __str__(self):
        return "{}:{}, locked: {}".format(self.namespace, self.name, self.is_locked)

    def save(self, *args, **kwargs):
        self.slugify()
        return super(Hub, self).save(*args, **kwargs)

    def get_subscriber_count(self):
        return self.subscriber_count

    def slugify(self):
        if not self.slug:
            self.slug = slugify(self.name.lower())
            # We only want slugs that equal exactly or are appended with "-{number}"
            hub_slugs = Hub.objects.filter(
                models.Q(slug=self.slug)
                | models.Q(slug__regex=r"^{}-\d+$".format(self.slug))
            ).order_by(models.F("slug_index").asc(nulls_first=True))

            if hub_slugs.exists():
                last_slug = hub_slugs.last()
                if not last_slug.slug_index:
                    self.slug_index = 1
                else:
                    self.slug_index = last_slug.slug_index + 1
                self.slug = self.slug + "-" + str(self.slug_index)
        return self.slug

    def get_discussion_count(self):
        return (
            self.papers.filter(is_removed=False).aggregate(
                disc=Sum("discussion_count")
            )["disc"]
            or 0
        )

    def get_doc_count(self):
        return self.papers.filter(is_removed=False).count()

    def get_subscribers_count(self):
        return self.subscribers.filter(is_suspended=False).count()

    def get_editor_permission_groups(self):
        return self.permissions.filter(
            (
                Q(access_type=ASSISTANT_EDITOR)
                | Q(access_type=ASSOCIATE_EDITOR)
                | Q(access_type=SENIOR_EDITOR)
            ),
        ).all()

    # There are a handful of OpenAlex subfields that have duplicate names
    # but different IDs. This method will ensure that a corresponding hub is returned properly
    @classmethod
    def get_from_subfield(cls, subfield):
        return Hub.objects.get(
            (Q(name__iexact=subfield.display_name) | Q(subfield_id=subfield.id))
            & ~Q(namespace="journal")
        )

    @classmethod
    def create_or_update_hub_from_concept(cls, concept):
        hub, _ = Hub.objects.get_or_create(
            name__iexact=concept.display_name,
            defaults={
                "name": concept.display_name,
            },
        )

        hub.concept_id = concept.id
        hub.description = concept.description
        hub.save()

        return hub

    @property
    def paper_count_indexing(self):
        return self.get_paper_count()

    @property
    def subscriber_count_indexing(self):
        return self.get_subscribers_count()

    @property
    def editor_permission_groups(self):
        return self.get_editor_permission_groups()

    def unlock(self):
        self.is_locked = False
        self.save(update_fields=["is_locked"])


class HubMembership(models.Model):
    hub = models.ForeignKey(Hub, on_delete=models.CASCADE)
    user = models.ForeignKey("user.User", on_delete=models.CASCADE)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

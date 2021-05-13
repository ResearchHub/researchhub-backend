from django.db import models
from django.db.models import Sum

from slugify import slugify

HELP_TEXT_IS_REMOVED = (
    'Hides the hub because it is not allowed.'
)

def get_default_hub_category():
    """Get or create a default value for the hub categories"""

    return HubCategory.objects.get_or_create(category_name='Other')[0]


class HubCategory(models.Model):
    """A grouping of hubs, organized by category"""

    def __str__(self):
        return self.category_name

    def __int__(self):
        return self.id

    category_name = models.CharField(max_length=1024, unique=True)


class Hub(models.Model):
    """A grouping of papers, organized by subject"""

    UNLOCK_AFTER = 14

    name = models.CharField(max_length=1024, unique=True)
    description = models.TextField(default='')
    hub_image = models.FileField(
        max_length=1024,
        upload_to='uploads/hub_images/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    slug = models.CharField(max_length=256, unique=True, blank=True, null=True)
    slug_index = models.IntegerField(blank=True, null=True)
    acronym = models.CharField(max_length=255, default='', blank=True)
    is_locked = models.BooleanField(default=False)
    subscribers = models.ManyToManyField(
        'user.User',
        related_name='subscribed_hubs',
        through='HubMembership'
    )
    category = models.ForeignKey(
        HubCategory,
        on_delete=models.CASCADE,
        default=get_default_hub_category
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    subscriber_count = models.IntegerField(default=0)
    paper_count = models.IntegerField(default=0)
    discussion_count = models.IntegerField(default=0)

    is_removed = models.BooleanField(
        default=False,
        help_text=HELP_TEXT_IS_REMOVED
    )

    def __str__(self):
        return '{}, locked: {}'.format(self.name, self.is_locked)

    def save(self, *args, **kwargs):
        self.name = self.name.lower()
        self.slugify()
        return super(Hub, self).save(*args, **kwargs)

    def get_subscriber_count(self):
        return self.subscriber_count

    def slugify(self):
        if not self.slug:
            self.slug = slugify(self.name)
            hub_slugs = Hub.objects.filter(
                slug__startswith=self.slug
            ).order_by('slug_index')
            if hub_slugs.exists():
                last_slug = hub_slugs.last()
                if not last_slug.slug_index:
                    self.slug_index = 1
                else:
                    self.slug_index = last_slug.slug_index + 1
                self.slug = self.slug + '-' + str(self.slug_index)
        return self.slug

    def get_discussion_count(self):
        return self.papers.filter(is_removed=False).aggregate(disc=Sum('discussion_count'))['disc'] or 0

    def get_paper_count(self):
        return self.papers.filter(is_removed=False).count()

    def get_subscribers_count(self):
        return self.subscribers.filter(is_suspended=False).count()

    @property
    def paper_count_indexing(self):
        return self.get_paper_count()

    @property
    def subscriber_count_indexing(self):
        return self.get_subscribers_count()

    def unlock(self):
        self.is_locked = False
        self.save(update_fields=['is_locked'])


class HubMembership(models.Model):
    user = models.ForeignKey('user.User', on_delete=models.CASCADE)
    hub = models.ForeignKey(Hub, on_delete=models.CASCADE)

    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

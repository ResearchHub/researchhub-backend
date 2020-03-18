from django.db import models
from django.db.models import Q, Count

from paper.models import Vote as PaperVote
from slugify import slugify


class Hub(models.Model):
    UNLOCK_AFTER = 14

    name = models.CharField(max_length=1024, unique=True)
    slug = models.CharField(max_length=256, unique=True, blank=True, null=True)
    slug_index = models.IntegerField(blank=True, null=True)
    acronym = models.CharField(max_length=255, default='', blank=True)
    is_locked = models.BooleanField(default=False)
    subscribers = models.ManyToManyField(
        'user.User',
        related_name='subscribed_hubs'
    )
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return '{}, locked: {}'.format(self.name, self.is_locked)

    def save(self, *args, **kwargs):
        self.name = self.name.lower()
        self.slugify()
        return super(Hub, self).save(*args, **kwargs)
    
    def slugify(self):
        if not self.slug:
            self.slug = slugify(self.name)
            hub_slugs = Hub.objects.filter(slug__startswith=self.slug).order_by('slug_index')
            if hub_slugs.exists():
                if not hub_slugs.first().slug_index:
                    self.slug_index = 1
                else:
                    self.slug_index = hub_slugs.first().slug_index + 1
                self.slug = self.slug + '-' + str(self.slug_index)
        return self.slug

    @property
    def subscriber_count_indexing(self):
        return len(self.subscribers.all())

    def unlock(self):
        self.is_locked = False
        self.save()

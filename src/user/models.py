from django.db import models
from django.contrib.auth.models import AbstractUser
from django.dispatch import receiver
from storages.backends.s3boto3 import S3Boto3Storage


class User(AbstractUser):
    """
    User objects have the following fields by default:
        https://docs.djangoproject.com/en/2.2/ref/contrib/auth/#django.contrib.auth.models.User
    """
    reputation = models.IntegerField(default=100)
    upload_tutorial_complete = models.BooleanField(default=False)
    has_seen_first_vote_modal = models.BooleanField(default=False)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    bookmarks = models.ManyToManyField(
        'paper.Paper',
        related_name='users_who_bookmarked'
    )

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        # A unique constraint is enforced on the username on the database
        # level. This line is used to ensure usernames are not empty without
        # requiring the client to enter a value in this field. It also forces
        # emails to be unique.
        #
        # If we want to allow client specified usernames, simply remove the
        # set username line.

        self.username = self.email
        super().save(*args, **kwargs)

    def set_has_seen_first_vote_modal(self, has_seen):
        self.has_seen_first_vote_modal = has_seen
        self.save()


@receiver(models.signals.post_save, sender=User)
def attach_author(sender, instance, created, *args, **kwargs):
    if created:
        Author.objects.create(
            user=instance,
            first_name=instance.first_name,
            last_name=instance.last_name,
        )


class University(models.Model):
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=255)
    state = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name}_{self.city}'


class EmailPreference(models.Model):
    email = models.CharField(max_length=255, unique=True)
    subscribe = models.BooleanField(default=False)
    opt_out = models.BooleanField(default=False)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.email}'


class ProfileImageStorage(S3Boto3Storage):
    def __init__(self):
        super(ProfileImageStorage, self).__init__()

    def url(self, name):
        if 'http' in name:
            return name
        else:
            return super(ProfileImageStorage, self).url(name)


fs = ProfileImageStorage()


class Author(models.Model):
    user = models.OneToOneField(
        User,
        related_name='author_profile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    first_name = models.CharField(max_length=30)  # Same max_length as User
    last_name = models.CharField(max_length=150)  # Same max_length as User
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    description = models.TextField(
        null=True,
        blank=True
    )
    profile_image = models.FileField(
        upload_to='uploads/author_profile_images/%Y/%m/%d',
        max_length=1024,
        default=None,
        null=True,
        blank=True,
        storage=fs
    )
    university = models.ForeignKey(
        University,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    facebook = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    twitter = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True
    )
    linkedin = models.CharField(
        max_length=255,
        default=None,
        null=True,
        blank=True
    )

    def __str__(self):
        university = self.university
        if university is None:
            university_name = ''
            university_city = ''
        else:
            university_name = university.name
            university_city = university.city
        return (f'{self.first_name}_{self.last_name}_{university_name}_'
                f'{university_city}')

    @property
    def profile_image_indexing(self):
        if self.profile_image is not None:
            try:
                return self.profile_image.url
            except ValueError:
                return str(self.profile_image)
        return None

    @property
    def university_indexing(self):
        if self.university is not None:
            return self.university
        return None

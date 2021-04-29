from allauth.socialaccount.models import SocialAccount
from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models
from django.db.models import Sum

from user.related_models.profile_image_storage import ProfileImageStorage
from user.related_models.school_model import University
from user.related_models.user_model import User

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
    author_score = models.IntegerField(default=0)
    university = models.ForeignKey(
        University,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    orcid_id = models.CharField(
        max_length=1024,
        default=None,
        null=True,
        blank=True,
        unique=True
    )
    orcid_account = models.ForeignKey(
        SocialAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    education = ArrayField(
        JSONField(
            blank=True,
            null=True
        ),
        default=list,
        blank=True,
        null=True
    )
    headline = JSONField(
        blank=True,
        null=True
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
    academic_verification = models.BooleanField(default=None, null=True)

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
    def full_name(self):
        return self.first_name + ' ' + self.last_name

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

    def calculate_score(self):
        aggregated_score = (
          self.authored_papers.aggregate(total_score=Sum('score'))
        )
        aggregated_discussion_count = (
          self.authored_papers.aggregate(total_score=Sum('discussion_count'))
        )
        paper_count = self.authored_papers.count()
        paper_scores = 0
        if aggregated_score['total_score']:
            paper_scores = aggregated_score['total_score']

        if aggregated_discussion_count['total_score']:
            paper_scores += 2 * aggregated_discussion_count['total_score']

        return paper_scores + paper_count / 10

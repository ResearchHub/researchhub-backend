import requests

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.contrib.contenttypes.models import ContentType
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from researchhub_access_group.constants import (
    ADMIN
)
from researchhub_access_group.models import Permission
from user.constants.organization_constants import (
    PERSONAL
)
from user.models import User, Organization


class Command(BaseCommand):
    """
    Creates organizations for all pre-existing users
    """

    def handle(self, *args, **options):
        users = User.objects.filter(organization__isnull=True)
        for user in users.iterator():
            print(user.email)
            suffix = get_random_string(length=32)
            name = f"{user.first_name} {user.last_name}'s Notebook"
            slug = slugify(name)
            if not slug:
                slug += suffix
            if Organization.objects.filter(slug__icontains=slug).exists():
                slug += f'-{suffix}'

            content_type = ContentType.objects.get_for_model(Organization)
            org = Organization.objects.create(
                name=name,
                org_type=PERSONAL,
                slug=slug,
                user=user,
            )
            Permission.objects.create(
                access_type=ADMIN,
                content_type=content_type,
                object_id=org.id,
                organization=org,
                user=user,
            )

            profile_image = user.author_profile.profile_image
            request = requests.get(profile_image.url)
            if request.status_code == 200:
                profile_image_content = request.content
                profile_image_file = ContentFile(profile_image_content)
                org.cover_image.save(
                    f'org_image_{user.id}_{slug}.png',
                    profile_image_file,
                    save=True
                )

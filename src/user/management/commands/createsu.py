from django.core.management.base import BaseCommand
from user.models import User
import os


class Command(BaseCommand):

    def handle(self, *args, **options):
        ADMIN_PASS = os.environ.get('ADMIN_PASS', '')
        if not User.objects.filter(email='admin@quantfive.org').exists():
            User.objects.create_superuser(
                'admin',
                'admin@quantfive.org',
                ADMIN_PASS
            )

from django.core.management.base import BaseCommand
from hub.models import HubCategory


class Command(BaseCommand):

    def handle(self, *args, **options):
        categories = [
            'Biology',
            'Medicine',
            'Computer Science',
            'Physics',
            'Math',
            'Chemistry',
            'Engineering',
            'Social and Behavioral Sciences',
            'Arts and Humanities',
            'Other',
        ]
        for category_name in categories:
            if not HubCategory.objects.filter(category_name=category_name).exists():
                category = HubCategory(category_name=category_name)
                category.save()

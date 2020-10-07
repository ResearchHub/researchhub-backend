from django.core.management.base import BaseCommand
from hub.models import Hub, HubCategory


class Command(BaseCommand):

    def update_hub_category(self, hub_name, category_name):
        """
        Updates the category of a hub.

        Parameters:
            hub_name (str): The name of the hub to update.
            category_name (str): The name of the category we're updating to.

        """
        if Hub.objects.filter(name=hub_name).exists():
            hub = Hub.objects.get(name=hub_name)
            category = HubCategory.objects.get(category_name=category_name)
            hub.category = category
            hub.save()

    def handle(self, *args, **options):
        categories_and_hubs = {
            'Math': [
                'mathematics',
                'abstract algebra',
                'data analysis, statistics and probability',
                'number theory',
                'logic',
            ],
            'Physics': [
                'physics',
                'astrophysics',
                'atomic physics',
                'fluid dynamics',
                'nuclear theory',
                'optics',
                'quantum physics',
            ],
            'Computer Science': [
                'computer science',
                'artificial intelligence',
                'distributed, parallel, and cluster computing',
                'cryptography and security',
                'blockchain',
                'cryptocurrency',
                'programming languages',
                'data structures and algorithms',
                'human-computer interaction',
                'machine learning',
                'software engineering',
            ],
            'Biology': [
                'biology',
                'bioinformatics',
                'biomolecules',
                'biophysics',
                'biochemistry',
                'botany',
                'cancer-biology',
                'cell biology',
                'developmental-biology',
                'ecology',
                'environmental science',
                'evolutionary-biology',
                'genetics',
                'geology',
                'microbiology',
                'molecular biology',
                'systems-biology',
                'paleontology',
                'pathology',
                'pharmacology-and-toxicology',
                'physiology',
                'neuroscience',
                'synthetic biology',
                'zoology',
            ],
            'Medicine': [
                'anesthesiology',
                'medicine',
                'covid-19 / coronavirus',
                'clinical-trials',
                'dermatology',
                'epidemiology',
                'endocrinology',
                'immunology',
                'internal medicine',
                'kinesiology',
                'longevity',
                'mental illness',
                'nutrition',
            ],
            'Chemistry': [
                'chemistry',
                'chemical physics',
                'materials science',
            ],
            'Engineering': [
                'engineering',
                'biotechnology',
                'chemical engineering',
                'robotics',
                'emerging technologies',
                'photovoltaics',
            ],
            'Social and Behavioral Sciences': [
                'sociology',
                'psychology',
                'political science',
                'geography',
                'legal',
                'economics',
                'general finance',
                'methodology',
                'metascience',
            ],
            'Arts and Humanities': [
                'art',
                'design',
                'philosophy',
                'history',
                'general literature',
                'anthropology',
            ],
            'Other': [
                'other',
            ],
        }

        for category_name in categories_and_hubs:
            for hub_name in categories_and_hubs[category_name]:
                self.update_hub_category(hub_name, category_name)

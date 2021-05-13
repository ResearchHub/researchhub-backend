from django.core.management.base import BaseCommand
from hub.models import Hub


class Command(BaseCommand):

    def handle(self, *args, **options):
        hubs_to_delete = [
            # Math
            'general mathematics',
            'mathematical software',
            'statistics theory',
            'other statistics',
            'logic in computer science',

            # Physics
            'general physics',
            'applied physics',
            'classical physics',
            'computational physics',
            'superconductivity',
            'accelerator physics',
            'foundations of physics',
            'high energy physics - experiment',
            'medical physics',
            'physics and society',
            'atmospheric and oceanic physics',
            'earth and planetary astrophysics',
            'cosmology and nongalactic astrophysics',
            'quantum gravity',

            # Computer Science
            'other computer science',
            'computers and society',
            'digital libraries',
            'sound',
            'cybersecurity',
            'ethereum',
            'computation and language',
            'human computer interaction',

            # Biology
            'agronomy',
            'lipid',
            'biological physics',
            'plant biology',
            'plant-biology',
            'plant science',
            'plant biotechnology',
            'plant pathology',
            'cell-biology',
            'cell signal transduction',
            'genomics',
            'microbiome',
            'molecular-biology',
            'molecular networks',
            'drug discovery',
            'synthetic-biology',

            # Medicine
            'medical sciences',

            # Chemistry
            'material science',

            # Engineering
            'bioengineering',

            # Social and Behavioral Sciences
            'social and information networks',
            'populations and evolution',
            'general economics',
            'theoretical economics',
            'business',
            'e-commerce',
            'mathematical finance',
            'computational finance',
            'quantitative methods',
            'scientific-communication-and-education',

            # Other
            'general',
        ]

        for hub_name in hubs_to_delete:
            if Hub.objects.filter(name=hub_name).exists():
                hub = Hub.objects.get(name=hub_name)
                hub.delete()

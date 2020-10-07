from django.core.management.base import BaseCommand
from django.db.models import Sum
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

    def migrate_content(self, from_hub_name, to_hub_name):
        """
        Migrates content (subscribers, papers, user actions, reputation
        distributions) between hubs.

        Parameters:
            from_hub_name (str): The name of the hub we are migrating the
            content out of.
            to_hub_name (str): The name of hub we are migrating the content into.

        """
        if (Hub.objects.filter(name=from_hub_name).exists() and
            Hub.objects.filter(name=to_hub_name).exists()):
            from_hub = Hub.objects.get(name=from_hub_name)
            to_hub = Hub.objects.get(name=to_hub_name)

            for subscriber in from_hub.subscribers.all():
                subscriber.subscribed_hubs.remove(from_hub)
                subscriber.subscribed_hubs.add(to_hub)

            for paper in from_hub.papers.all():
                paper.hubs.remove(from_hub)
                paper.hubs.add(to_hub)

            for user_action in from_hub.actions.all():
                user_action.hubs.remove(from_hub)
                user_action.hubs.add(to_hub)

            for reputation_distribution in from_hub.reputation_records.all():
                reputation_distribution.hubs.remove(from_hub)
                reputation_distribution.hubs.add(to_hub)

            print(f'finished migrating {from_hub_name} -> {to_hub_name}')

    def handle(self, *args, **options):
        # create-categories.py
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

        # categorize-hubs.py
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

        # migrate-hubs.py
        # Math
        self.migrate_content('general mathematics', 'mathematics')
        self.migrate_content('mathematical software', 'mathematics')
        self.migrate_content('statistics theory',
                             'data analysis, statistics and probability')
        self.migrate_content('other statistics',
                             'data analysis, statistics and probability')
        self.migrate_content('logic in computer science', 'logic')

        # Physics
        self.migrate_content('general physics', 'physics')
        self.migrate_content('applied physics', 'physics')
        self.migrate_content('classical physics', 'physics')
        self.migrate_content('computational physics', 'physics')
        self.migrate_content('superconductivity', 'physics')
        self.migrate_content('accelerator physics', 'physics')
        self.migrate_content('foundations of physics', 'physics')
        self.migrate_content('high energy physics - experiment', 'physics')
        self.migrate_content('medical physics', 'physics')
        self.migrate_content('physics and society', 'physics')
        self.migrate_content('atmospheric and oceanic physics', 'physics')
        self.migrate_content(
            'earth and planetary astrophysics', 'astrophysics')
        self.migrate_content(
            'cosmology and nongalactic astrophysics', 'astrophysics')
        self.migrate_content('quantum gravity', 'quantum physics')

        # Computer Science
        self.migrate_content('other computer science', 'computer science')
        self.migrate_content('computers and society', 'computer science')
        self.migrate_content('digital libraries', 'computer science')
        self.migrate_content('sound', 'computer science')
        self.migrate_content('cybersecurity', 'cryptography and security')
        self.migrate_content('ethereum', 'cryptocurrency')
        self.migrate_content('computation and language',
                             'programming languages')
        self.migrate_content('human computer interaction',
                             'human-computer interaction')

        # Biology
        self.migrate_content('agronomy', 'biology')
        self.migrate_content('lipid', 'biomolecules')
        self.migrate_content('biological physics', 'biophysics')
        self.migrate_content('plant biology', 'botany')
        self.migrate_content('plant-biology', 'botany')
        self.migrate_content('plant science', 'botany')
        self.migrate_content('plant biotechnology', 'botany')
        self.migrate_content('plant pathology', 'botany')
        self.migrate_content('cell-biology', 'cell biology')
        self.migrate_content('cell signal transduction', 'cell biology')
        self.migrate_content('genomics', 'genetics')
        self.migrate_content('microbiome', 'microbiology')
        self.migrate_content('molecular-biology', 'molecular biology')
        self.migrate_content('molecular networks', 'systems-biology')
        self.migrate_content('drug discovery', 'pharmacology-and-toxicology')
        self.migrate_content('synthetic-biology', 'synthetic biology')

        # Medicine
        self.migrate_content('medical sciences', 'medicine')

        # Chemistry
        self.migrate_content('material science', 'materials science')

        # Engineering
        self.migrate_content('bioengineering', 'biotechnology')

        # Social and Behavioral Sciences
        self.migrate_content('social and information networks', 'sociology')
        self.migrate_content('populations and evolution', 'sociology')
        self.migrate_content('general economics', 'economics')
        self.migrate_content('theoretical economics', 'economics')
        self.migrate_content('business', 'economics')
        self.migrate_content('e-commerce', 'economics')
        self.migrate_content('mathematical finance', 'general finance')
        self.migrate_content('computational finance', 'general finance')
        self.migrate_content('quantitative methods', 'methodology')
        self.migrate_content(
            'scientific-communication-and-education', 'metascience')

        # Other
        self.migrate_content('general', 'other')

        # delete-hubs.py
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

        # update-hub-counts.py
        all_hubs = Hub.objects.all()
        for hub in all_hubs:
            print('calculating subscriber_count for', hub.name)
            hub.subscriber_count = hub.subscribers.count()
            print('calculating paper_count for', hub.name)
            hub.paper_count = hub.papers.count()
            print('calculating discussion_count for', hub.name)
            annotation = Hub.objects.filter(id=hub.id).annotate(hub_discussion_count=Sum('papers__discussion_count'))
            hub.discussion_count = annotation.first().hub_discussion_count or 0
            hub.save()

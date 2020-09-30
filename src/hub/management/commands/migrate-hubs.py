from django.core.management.base import BaseCommand
from hub.models import Hub


class Command(BaseCommand):

    def migrate_content(self, from_hub_name, to_hub_name):
        """
        Migrates content (subscribers, papers, user actions, reputation
        distributions) between hubs.

        Parameters:
            from_hub_name (str): The name of the hub we are migrating the
            content out of.
            to_hub_name (str): The name of hub we are migrating the content into.

        """
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

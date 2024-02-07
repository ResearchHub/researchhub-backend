from django.core.management.base import BaseCommand
from django.db.models import Q
from paper.models import Paper

class Command(BaseCommand):
    help = 'Mark duplicate papers with 0 discussion_count as removed'

    def handle(self, *args, **kwargs):
        batch_size = 100
        papers = Paper.objects.filter(
            is_removed=False,
            # must have at least one forward slash to be a valid DOI
            doi__contains='/',
        ).only('id', 'doi', 'discussion_count').iterator()
        to_update_ids = []

        for paper in papers:
            if paper.doi:
                normalized_doi = paper.doi.lower().strip().replace('http://', 'https://').replace('https://dx.doi.org/', '').replace('https://doi.org/', '').replace('dx.doi.org/', '').replace('doi.org/', '').strip()

                duplicate_papers = Paper.objects.filter(
                    Q(doi__iexact=normalized_doi) |
                    Q(doi__iexact=f'doi.org/{normalized_doi}') |
                    Q(doi__iexact=f'https://doi.org/{normalized_doi}') |
                    Q(doi__iexact=f'dx.doi.org/{normalized_doi}') |
                    Q(doi__iexact=f'https://dx.doi.org/{normalized_doi}'),
                    is_removed=False
                ).exclude(id=paper.id)

                # Exclude papers that have non-zero discussion counts or related CitationEntry
                # Since these are probably (in use)
                duplicate_papers = duplicate_papers.filter(discussion_count=0).exclude(
                    unified_document__citation_entries__isnull=False
                ).values_list('id', flat=True)
                to_update_ids.extend(duplicate_papers)
                
                if len(to_update_ids) >= batch_size:
                    Paper.objects.filter(id__in=to_update_ids).update(is_removed=True)
                    self.stdout.write(f'Updated {len(to_update_ids)} papers as removed.')
                    to_update_ids = []

        if to_update_ids:
            Paper.objects.filter(id__in=to_update_ids).update(is_removed=True)
            self.stdout.write(f'Updated {len(to_update_ids)} papers as removed.')

        self.stdout.write(self.style.SUCCESS('Successfully marked duplicate papers with 0 discussion count as removed in batches.'))

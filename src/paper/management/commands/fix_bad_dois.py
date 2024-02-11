from django.core.management.base import BaseCommand
from django.db.models import Q
from paper.models import Paper

class Command(BaseCommand):
    help = 'Correct DOIs for papers with specific invalid DOIs or missing prefixes.'

    def handle(self, *args, **kwargs):
        self.update_papers_with_malformed_dois_and_arxiv_urls()
        self.update_papers_with_arxiv_dois()
        self.stdout.write(self.style.SUCCESS("Finished updating papers with corrected DOIs."))

    def update_papers_with_malformed_dois_and_arxiv_urls(self):
        """Handles papers with a malformed DOI and an ArXiv URL."""
        papers = Paper.objects.filter(
            ~Q(doi__icontains='/'), 
            ~Q(doi__icontains='arxiv'), 
            doi__isnull=False, 
            url__icontains='arxiv.org'
        )
        self.process_arxiv_papers(papers)

    def update_papers_with_arxiv_dois(self):
        """
        Handles papers where the DOI starts with:
        - 'arXiv.'
        - 'arxiv.'
        - 'arXiv:'
        - 'arxiv:'
        """
        papers = Paper.objects.filter(
            Q(doi__startswith='arXiv.') |
            Q(doi__startswith='arxiv.') |
            Q(doi__startswith='arXiv:') |
            Q(doi__startswith='arxiv:')
        )
        self.process_arxiv_papers(papers)

    def process_arxiv_papers(self, papers):
        to_update = []
        for paper in papers.iterator():
            arxiv_id = self.extract_arxiv_id(paper)
            if arxiv_id:
                paper.doi = f"10.48550/arXiv.{arxiv_id}"
                to_update.append(paper)
            else:
                # see if the url is a doi.org link
                if 'doi.org' in paper.url:
                    doi = paper.url.split('doi.org/')[-1]
                    # make sure it's arXiv. and not arXiv:
                    paper.doi = doi.replace('arXiv:', 'arXiv.')
                    to_update.append(paper)

            if len(to_update) >= 100:
                print(f'Updating {len(to_update)} papers...')
                Paper.objects.bulk_update(to_update, ['doi'])
                to_update.clear()

        if to_update:
            print(f'Updating {len(to_update)} papers...')
            Paper.objects.bulk_update(to_update, ['doi'])

    def extract_arxiv_id(self, paper):
        """Extracts the ArXiv ID from the paper's DOI or URL."""
        if paper.doi.startswith('arXiv.') or paper.doi.startswith('arxiv.'):
            return paper.doi.split('.')[-1]
        elif paper.doi.startswith('arXiv:') or paper.doi.startswith('arxiv:'):
            return paper.doi.split(':')[-1]
        elif 'arxiv.org' in paper.url:
            parts = paper.url.split('/')
            if 'abs' in parts or 'pdf' in parts:
                return parts[-1].replace('.pdf', '')
        return None

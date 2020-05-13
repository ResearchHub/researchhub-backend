from django.core.management.base import BaseCommand

from paper.models import Paper


class Command(BaseCommand):
    key = 'https://arxiv.org/abs/'

    def handle(self, *args, **options):
        papers = Paper.objects.filter(
            url__isnull=False,
            external_source='arxiv'
        )
        paper_count = len(papers)
        for idx, paper in enumerate(papers):
            print(f'Setting arxiv id: {idx + 1} / {paper_count}')
            if (
                (self.key in paper.url)
                and (paper.alternate_ids.get('arxiv') is None)
            ):
                arxiv_id = self._get_arxiv_id_from_url(paper.url)
                alternate_ids = paper.alternate_ids
                alternate_ids['arxiv'] = arxiv_id
                paper.alternate_ids = alternate_ids
                paper.save()

    def _get_arxiv_id_from_url(self, url):
        parts = url.split(self.key)
        try:
            if parts[0] == '':
                return 'arXiv:' + parts[1]
            else:
                return None
        except Exception:
            return None

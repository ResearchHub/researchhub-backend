from django.core.management.base import BaseCommand

from hub.models import Hub
from paper.related_models.paper_model import Paper


class Command(BaseCommand):
    """
    Assigns papers to their respective journal hubs based on the `external_source`
    field on the paper.
    """

    def handle(self, *args, **options):
        def get_journal_hub(journal):
            return Hub.objects.get(name=journal, namespace=Hub.Namespace.JOURNAL)

        source_to_journalhub = {
            "arXiv (Cornell University)": get_journal_hub("arxiv"),
            "bioRxiv (Cold Spring Harbor Laboratory)": get_journal_hub("biorxiv"),
            "medRxiv (Cold Spring Harbor Laboratory)": get_journal_hub("medrxiv"),
            "ChemRxiv": get_journal_hub("chemrxiv"),
            "Research Square (Research Square)": get_journal_hub("research square"),
            "OSF Preprints (OSF Preprints)": get_journal_hub("osf preprints"),
            "PeerJ": get_journal_hub("peerj"),
            "Authorea (Authorea)": get_journal_hub("authorea"),
            "SSRN Electronic Journal": get_journal_hub("ssrn"),
        }

        papers = (
            Paper.objects.filter(external_source__in=source_to_journalhub.keys())
            .exclude(
                # exclude papers that are already associated with a journal hub
                id__in=Paper.objects.values("id").filter(
                    hubs__namespace=Hub.Namespace.JOURNAL
                )
            )
            .only("id", "external_source", "hubs")
        )

        for paper in papers.iterator(chunk_size=1000):
            journal_hub = source_to_journalhub[paper.external_source]
            if not paper.hubs.filter(id=journal_hub.id).exists():
                paper.hubs.add(journal_hub)
                print(f"Added paper {paper.id} to hub {journal_hub.name}")

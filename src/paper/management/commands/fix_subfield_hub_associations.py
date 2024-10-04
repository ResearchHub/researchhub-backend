from django.core.management.base import BaseCommand

from paper.models import Paper

subfields_to_correct_subfields = {
    106972: 75211,
    95288: 191,
    112745: 3454,
    93567: 17,
    140669: 75216,
    97902: 201,
    93536: 63243,
    94139: 205,
    94290: 206,
    215275: 9025,
}


class Command(BaseCommand):
    """
    One-off command to correct the subfield hub associations for papers that
    have incorrect subfield hubs (all lowercase hub names).
    """

    def handle(self, *args, **options):
        papers = Paper.objects.filter(
            hubs__id__in=subfields_to_correct_subfields.keys()
        ).only("hubs")

        for paper in papers.iterator(chunk_size=1000):
            for hub in paper.hubs.all():
                if hub.id in subfields_to_correct_subfields.keys():
                    correct_hub = subfields_to_correct_subfields[hub.id]
                    print(
                        f"Paper {paper.id} (doc {paper.unified_document.id}): Replacing hub '{hub.name}', ID=({hub.id}) with ID={correct_hub}"
                    )
                    paper.hubs.add(correct_hub)
                    paper.hubs.remove(hub)
                    paper.unified_document.hubs.add(correct_hub)
                    paper.unified_document.hubs.remove(hub)
                    paper.save(update_fields=["hub"])

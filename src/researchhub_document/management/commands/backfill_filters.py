from threading import Thread

from django.core.management.base import BaseCommand
from django.db import connection

from researchhub_document.models import DocumentFilter, ResearchhubUnifiedDocument


class Command(BaseCommand):
    def handle(self, *args, **options):
        def add_filters(start, end):
            print(f"STARTING - {start} : {end}")
            qs = ResearchhubUnifiedDocument.objects.filter(id__gte=start, id__lt=end)
            updates = []
            for i, obj in enumerate(qs.iterator()):
                doc_filter = DocumentFilter.objects.create()
                obj.document_filter = doc_filter
                updates.append(obj)

                if i % 1000 == 0:
                    print(f"Starting ID - {start} - {i}")
                    ResearchhubUnifiedDocument.objects.bulk_update(
                        updates, ["document_filter"]
                    )
                    updates = []

            ResearchhubUnifiedDocument.objects.bulk_update(updates, ["document_filter"])
            print("COMPLETED")
            connection.close()

        def migrate():
            CHUNK_SIZE = 50000
            qs = ResearchhubUnifiedDocument.objects.all().order_by("id")
            start = qs.first().id
            end = qs.last().id

            for i in range(start, end + CHUNK_SIZE, CHUNK_SIZE):
                t = Thread(target=add_filters, args=(i, i + CHUNK_SIZE))
                t.daemon = True
                t.start()
                t.join()

        migrate()

from threading import Thread

from django.core.management.base import BaseCommand
from django.db import connection

from researchhub_document.models import DocumentFilter


class Command(BaseCommand):
    def handle(self, *args, **options):
        def update_filters(start, end):
            print(f"STARTING - {start} : {end}")
            qs = DocumentFilter.objects.filter(id__gte=start, id__lt=end)
            for i, obj in enumerate(qs.iterator()):
                if i % 1000 == 0:
                    print(f"Starting ID - {start} - {i}")

                obj.update_filter()

            print("COMPLETED")
            connection.close()

        def update():
            CHUNK_SIZE = 25000
            qs = DocumentFilter.objects.all().order_by("id")
            start = qs.first().id
            end = qs.last().id

            threads = []
            for i in range(start, end + CHUNK_SIZE, CHUNK_SIZE):
                t = Thread(target=update_filters, args=(i, i + CHUNK_SIZE))
                t.daemon = True
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

        update()

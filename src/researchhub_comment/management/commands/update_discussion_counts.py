from threading import Thread

from django.core.management.base import BaseCommand
from django.db.models import Q

from researchhub_document.models import ResearchhubUnifiedDocument


class Command(BaseCommand):
    def _update_discussion_count(self, start, end):
        docs = ResearchhubUnifiedDocument.objects.filter(id__gte=start, id__lt=end)
        doc_count = docs.count()
        for i, doc in enumerate(docs.iterator()):
            print(f"STARTING ID: {start} -- {i}/{doc_count}")
            try:
                item = doc.get_document()
                if hasattr(item, "rh_threads"):
                    count = item.rh_threads.filter(
                        (
                            Q(rh_comments__is_removed=False)
                            & Q(rh_comments__parent__isnull=True)
                        )
                        | (
                            Q(rh_comments__parent__is_removed=False)
                            & Q(rh_comments__parent__isnull=False)
                        )
                    ).count()
                    item.discussion_count = count
                    item.save(update_fields=["discussion_count"])
            except Exception as e:
                print(e)

    def handle(self, *args, **options):
        CHUNK_SIZE = 10000
        documents = ResearchhubUnifiedDocument.objects.all()
        start = 1263860
        end = documents.last().id

        py_threads = []
        for i in range(start, end + CHUNK_SIZE, CHUNK_SIZE):
            t = Thread(
                target=self._update_discussion_count,
                args=(i, i + CHUNK_SIZE),
            )
            t.daemon = True
            t.start()
            py_threads.append(t)

        for t in py_threads:
            t.join()

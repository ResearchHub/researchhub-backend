from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import PREREGISTRATION

documents = ResearchhubUnifiedDocument.objects.filter(document_type=PREREGISTRATION)

print(f"Deleting {len(documents)} unified documents...")

documents.delete()

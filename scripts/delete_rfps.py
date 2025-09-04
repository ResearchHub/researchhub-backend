from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import GRANT

rfps = ResearchhubUnifiedDocument.objects.filter(document_type=GRANT)

print(f"Deleting {rfps.count()} RFPs...")
rfps.delete()

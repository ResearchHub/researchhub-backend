from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import PREREGISTRATION

rfps = ResearchhubPost.objects.filter(document_type=PREREGISTRATION)
for rfp in rfps:
    print(f"Deleting RFP: {rfp.title} (ID: {rfp.id})")
    rfp.delete()
print("All RFPs deleted.")

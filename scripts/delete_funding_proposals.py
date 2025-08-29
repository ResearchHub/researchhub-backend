from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import GRANT

proposals = ResearchhubPost.objects.filter(document_type=GRANT)
for proposal in proposals:
    print(f"Deleting funding proposal: {proposal.title} (ID: {proposal.id})")
    proposal.delete()
print("All Proposals deleted.")

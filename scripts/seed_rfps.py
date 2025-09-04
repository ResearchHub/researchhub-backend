# Creating a Funding Proposal in ResearchHub

from django.utils.text import slugify

from hub.models import Hub
from purchase.models import Grant
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.constants.editor_type import CK_EDITOR
from user.models import User
from user.related_models.author_model import Author

user = User.objects.first()

papers = [
    {
        "title": "Request for Proposal: Research on Climate Change Impact",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[21]),
        "renderable_text": "This is a funding proposal for researching the impact of climate change on coastal ecosystems. We are requesting $100,000 to conduct a comprehensive study...",
        "created_by": user,
        "amount": 100000,
        "currency": "USD",
        "organization": "Climate Research Foundation",
        "description": "Funding for comprehensive climate change impact study on coastal ecosystems",
        "end_date": "2025-12-31",  # Optional end date
        "contacts": User.objects.filter(id__in=[1]),
    },
    {
        "title": "Request for Proposals - Cancer Biology Research Project",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[3, 201]),
        "renderable_text": "This is a funding proposal for researching cool stuff",
        "created_by": user,
        "amount": 99000,
        "currency": "USD",
        "organization": "Climate Research Foundation",
        "description": "Funding for comprehensive climate change impact study on coastal ecosystems",
        "end_date": "2025-11-21",  # Optional end date
        "contacts": User.objects.filter(id__in=[1]),
    },
    {
        "title": "Request for Proposals - Neuroscience Research Project",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[2]),
        "renderable_text": "our stuff is cooler.",
        "created_by": user,
        "amount": 88000,
        "currency": "USD",
        "organization": "Climate Research Foundation",
        "description": "even cooler stuff",
        "end_date": "2025-10-20",  # Optional end date
        "contacts": User.objects.filter(id__in=[1]),
    },
    {
        "title": "Request for Proposals - Bioinformatics & Genomics Research",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[17]),
        "renderable_text": "This is a funding proposal for researching the impact of climate change on coastal ecosystems. We are requesting $100,000 to conduct a comprehensive study...",
        "created_by": user,
        "amount": 77000,
        "currency": "USD",
        "organization": "Climate Research Foundation",
        "description": "Funding for comprehensive climate change impact study on coastal ecosystems",
        "end_date": "2025-09-20",  # Optional end date
        "contacts": User.objects.filter(id__in=[1]),
    },
    {
        "title": "Request for Proposals - Comprehensive Analysis of Water Quality in Urban U.S.",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[3]),
        "renderable_text": "This is a funding proposal for researching the impact of climate change on coastal ecosystems. We are requesting $100,000 to conduct a comprehensive study...",
        "created_by": user,
        "amount": 66000,
        "currency": "USD",
        "organization": "Climate Research Foundation",
        "description": "Funding for comprehensive climate change impact study on coastal ecosystems",
        "end_date": "2025-08-10",  # Optional end date
        "contacts": User.objects.filter(id__in=[1]),
    },
    {
        "title": "Quantum-Safe Blockchain: Building Secure and Future-Ready Decentralized Systems",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[80, 245]),
        "renderable_text": "This is a funding proposal for researching the impact of climate change on coastal ecosystems. We are requesting $100,000 to conduct a comprehensive study...",
        "created_by": user,
        "amount": 55000,
        "currency": "USD",
        "organization": "Climate Research Foundation",
        "description": "Funding for comprehensive climate change impact study on coastal ecosystems",
        "end_date": "2024-07-20",  # Optional end date
        "contacts": User.objects.filter(id__in=[1]),
    },
]

for paper in papers:
    # Create the unified document first (required)
    unified_document = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)

    unified_document.hubs.add(*paper["hubs"])
    # Create the funding proposal post
    rfp_post = ResearchhubPost.objects.create(
        created_by=paper["created_by"],
        document_type=GRANT,  # This marks it as a Request for Proposal
        title=paper["title"],
        slug=slugify(paper["title"]),
        renderable_text=paper["renderable_text"],
        editor_type=CK_EDITOR,
        unified_document=unified_document,
        doi=None,  # Optional: Add DOI if assigning one
        image=None,  # Optional: Add image URL or file
        preview_img=None,  # Optional: Add preview image
        bounty_type=None,  # Optional: Add bounty type if applicable
        note_id=None,  # Optional: Link to a note if applicable
        prev_version=None,  # For versioning
    )

    # Add authors (many-to-many relationship)
    authors = Author.objects.filter(id__in=[paper["author"].id])
    rfp_post.authors.set(authors)

    # Adding Grant Details
    # If you want to include specific funding details like amount, organization, and contacts.
    # Create grant with funding details
    grant = Grant.objects.create(
        created_by=paper["created_by"],
        unified_document=unified_document,
        amount=paper["amount"],
        currency=paper["currency"],
        organization=paper["organization"],
        description=paper["description"],
        end_date=paper["end_date"],  # Optional end date
    )

    # Add grant contacts if needed
    grant.contacts.set(paper["contacts"])

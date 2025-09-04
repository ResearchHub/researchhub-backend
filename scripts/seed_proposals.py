# Creating a Request for Proposal Requests Post in ResearchHub

from datetime import datetime, timedelta

import pytz
from django.contrib.contenttypes.models import ContentType
from django.utils.text import slugify

from hub.models import Hub
from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import MORALIS
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.services.fundraise_service import FundraiseService
from reputation.models import Bounty, Escrow
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.constants.editor_type import CK_EDITOR
from user.models import User
from user.related_models.author_model import Author

users = User.objects.all()
if not users.exists():
    User.objects.create_superuser(
        username="admin", email="admin@example.com", password="admin"
    )

user = User.objects.first()

hubs = Hub.objects.all()
if not hubs.exists():
    Hub.objects.create(id=2, name="Neuroscience", slug="neuroscience")
    Hub.objects.create(id=3, name="Biology", slug="biology")
    Hub.objects.create(
        id=17, name="Bioinformatics & Genomics", slug="bioinformatics-genomics"
    )
    Hub.objects.create(id=21, name="Climate Change", slug="climate-change")
    Hub.objects.create(id=80, name="Cryptocurrency", slug="cryptocurrency")
    Hub.objects.create(id=201, name="Cancer Biology", slug="cancer-biology")
    Hub.objects.create(id=245, name="Blockchain", slug="blockchain")


proposals = [
    {
        "title": f"Proposal: Accelerating What We Know About OCD: From Genes to Mice to Better Treatments",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[1, 2]),
        "renderable_text": "Accelerating What We Know About OCD: From Genes to Mice to Better Treatments We’re racing to turn human genetic discovery into a biological model to test new treatments. The challenge Obsess...",
        "created_by": user,
        "goal_amount": 100000,  # Goal amount in USD or specified currency
        "goal_currency": USD,
        "status": Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
        "bounty_type": Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
        "bounty_amount": 500,  # Bounty amount in RSC
        "expiration_date": datetime.now(pytz.UTC) + timedelta(days=10),
        "bounty_status": Bounty.OPEN,
        "amount_raised": 7000,
        "fundraise_status": Fundraise.OPEN,
    },
    {
        "title": "Proposal: Real-World Validation of Big Omics-Powered AI Drug Sensitivity Predictor for Acute Myeloid Leukemia Treatment",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[4, 5]),
        "renderable_text": "Real-World Validation of Big Omics-Powered AI Drug Sensitivity Predictor for Acute Myeloid Leukemia Treatment 1. Overview (1) scientific rationale and importance Despite the increasing use of targe...",
        "created_by": user,
        "goal_amount": 99000,  # Goal amount in USD or specified currency
        "goal_currency": USD,
        "status": Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
        "bounty_type": Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
        "bounty_amount": 1000,  # Bounty amount in RSC
        "expiration_date": datetime.now(pytz.UTC) + timedelta(days=20),
        "bounty_status": Bounty.OPEN,
        "amount_raised": 6000,
        "fundraise_status": Fundraise.OPEN,
    },
    {
        "title": "Proposal: Effects of psilocybin and related compounds on neuroprotection in human stroke",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[3]),
        "renderable_text": "Effects of psilocybin and related compounds on neuroprotection in human stroke 1. Principal investigators Ruslan Rust, PhD: RR Google Scholar Link Patrick D. Lyden, MD: PL Google Scholar Link Affil...",
        "created_by": user,
        "goal_amount": 88000,  # Goal amount in USD or specified currency
        "goal_currency": USD,
        "status": Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
        "bounty_type": Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
        "bounty_amount": 1500,  # Bounty amount in RSC
        "expiration_date": datetime.now(pytz.UTC) + timedelta(days=30),
        "bounty_status": Bounty.OPEN,
        "amount_raised": 5000,
        "fundraise_status": Fundraise.OPEN,
    },
    {
        "title": "Proposal: Untargeted Metabolomics, Antioxidant Capacity, and Total Phenolic Content of Honey produced by Apis mellifera in Guam and Okinawa",
        "author": user,
        "hubs": Hub.objects.filter(id__in=[21]),
        "renderable_text": "Untargeted Metabolomics, Antioxidant Capacity, and Total Phenolic Content of Honey produced by Apis mellifera in Guam and Okinawa 1. Project Overview Scientific rationale and importance: This is...",
        "created_by": user,
        "goal_amount": 88000,  # Goal amount in USD or specified currency
        "goal_currency": USD,
        "status": Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
        "bounty_type": Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
        "bounty_amount": 1500,  # Bounty amount in RSC
        "expiration_date": datetime.now(pytz.UTC) - timedelta(days=30),
        "bounty_status": Bounty.EXPIRED,
        "amount_raised": 4000,
        "fundraise_status": Fundraise.OPEN,
    },
]


def add_entries(fundraise_status=Fundraise.OPEN):
    unified_document = ResearchhubUnifiedDocument.objects.create(
        document_type=PREREGISTRATION
    )
    unified_document.hubs.add(*proposal["hubs"])

    funding_post = ResearchhubPost.objects.create(
        created_by=proposal["created_by"],
        document_type=PREREGISTRATION,  # Use PREREGISTRATION to appear in funding feed
        title=proposal["title"],
        slug=slugify(proposal["title"]),
        renderable_text=proposal["renderable_text"],
        editor_type=CK_EDITOR,
        unified_document=unified_document,
        bounty_type=proposal["bounty_type"],
        doi=None,  # Optional: Add DOI if assigning one
        image=None,  # Optional: Add image URL or file
        preview_img=None,  # Optional: Add preview image
        note_id=None,  # Optional: Link to a note if applicable
        prev_version=None,  # For versioning
    )

    # Add authors (many-to-many relationship)
    authors = Author.objects.filter(
        id__in=[proposal["author"].id]
    )  # Replace with actual author IDs
    funding_post.authors.set(authors)

    """
    Creating the Associated Fundraise (Required for Funding Feed)
    For proposal posts to appear in the funding feed, they need an associated
    Fundraise object
    """
    fundraise_service = FundraiseService()
    fundraise = fundraise_service.create_fundraise_with_escrow(
        user=proposal["created_by"],
        unified_document=unified_document,
        goal_amount=proposal["goal_amount"],  # Goal amount in USD or specified currency
        goal_currency=USD,
        status=fundraise_status,
    )

    fundraise.end_date = proposal["expiration_date"]
    fundraise.save(update_fields=["end_date"])

    """
    Creating the Associated Bounty (Optional)
    proposal posts can also have an associated bounty to incentivize responses:
    Create an escrow to hold the bounty funds
    """
    escrow = Escrow.objects.create(
        created_by=proposal["created_by"],
        hold_type=Escrow.BOUNTY,
        amount_holding=proposal["bounty_amount"],  # Amount in RSC tokens
        object_id=funding_post.id,
        content_type=ContentType.objects.get_for_model(funding_post),
    )

    # Create the bounty
    _ = Bounty.objects.create(
        created_by=proposal["created_by"],
        unified_document=unified_document,
        item_content_type=ContentType.objects.get_for_model(funding_post),
        item_object_id=funding_post.id,
        bounty_type=proposal["bounty_type"],  # REVIEW, ANSWER, or OTHER
        amount=proposal["bounty_amount"],  # Bounty amount in RSC
        escrow=escrow,
        expiration_date=proposal["expiration_date"],
        status=proposal["bounty_status"],
        parent=None,  # Set if this is a contribution to existing bounty
    )


# Seed fundraises proposals for each type.
for proposal in proposals:
    add_entries(fundraise_status=Fundraise.OPEN)
    add_entries(fundraise_status=Fundraise.CLOSED)
    add_entries(fundraise_status=Fundraise.COMPLETED)


# Prerequisites: Exchange Rate Setup
# Before creating posts with fundraises, ensure an exchange rate exists:
# Check if exchange rate exists, create if not
if not RscExchangeRate.objects.exists():
    RscExchangeRate.objects.create(
        price_source=MORALIS,
        rate=0.01,  # 1 RSC = $0.01 USD (adjust as needed)
    )

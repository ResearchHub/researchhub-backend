# Creating a Request for Proposal (RFP) Post in ResearchHub

## Basic Example

from datetime import datetime, timedelta

import pytz
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

print("seeding funding proposal ... ")

proposals = [
    {
        "title": "Proposal: Accelerating What We Know About OCD: From Genes to Mice to Better Treatments",
        "author": User.objects.get(id=1),
        "hubs": Hub.objects.filter(id__in=[1, 2]),
        "renderable_text": "Accelerating What We Know About OCD: From Genes to Mice to Better Treatments We’re racing to turn human genetic discovery into a biological model to test new treatments. The challenge Obsess...",
        "created_by": User.objects.get(id=1),
        "goal_amount": 100000,  # Goal amount in USD or specified currency
        "goal_currency": USD,
        "status": Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
        "bounty_type": Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
        "bounty_amount": 500,  # Bounty amount in RSC
        "expiration_date": datetime.now(pytz.UTC) + timedelta(days=30),
        "bounty_status": Bounty.OPEN,
        "amount_raised": 7000,
    },
    {
        "title": "Proposal: Real-World Validation of Big Omics-Powered AI Drug Sensitivity Predictor for Acute Myeloid Leukemia Treatment",
        "author": User.objects.get(id=1),
        "hubs": Hub.objects.filter(id__in=[1, 2]),
        "renderable_text": "Real-World Validation of Big Omics-Powered AI Drug Sensitivity Predictor for Acute Myeloid Leukemia Treatment 1. Overview (1) scientific rationale and importance Despite the increasing use of targe...",
        "created_by": User.objects.get(id=1),
        "goal_amount": 99000,  # Goal amount in USD or specified currency
        "goal_currency": USD,
        "status": Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
        "bounty_type": Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
        "bounty_amount": 1000,  # Bounty amount in RSC
        "expiration_date": datetime.now(pytz.UTC) + timedelta(days=20),
        "bounty_status": Bounty.OPEN,
        "amount_raised": 6000,
    },
    {
        "title": "Proposal: Effects of psilocybin and related compounds on neuroprotection in human stroke",
        "author": User.objects.get(id=1),
        "hubs": Hub.objects.filter(id__in=[1, 2]),
        "renderable_text": "Effects of psilocybin and related compounds on neuroprotection in human stroke 1. Principal investigators Ruslan Rust, PhD: RR Google Scholar Link Patrick D. Lyden, MD: PL Google Scholar Link Affil...",
        "created_by": User.objects.get(id=1),
        "goal_amount": 88000,  # Goal amount in USD or specified currency
        "goal_currency": USD,
        "status": Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
        "bounty_type": Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
        "bounty_amount": 1500,  # Bounty amount in RSC
        "expiration_date": datetime.now(pytz.UTC) + timedelta(days=10),
        "bounty_status": Bounty.OPEN,
        "amount_raised": 5000,
    },
    {
        "title": "Proposal: Untargeted Metabolomics, Antioxidant Capacity, and Total Phenolic Content of Honey produced by Apis mellifera in Guam and Okinawa",
        "author": User.objects.get(id=1),
        "hubs": Hub.objects.filter(id__in=[1, 2]),
        "renderable_text": "Untargeted Metabolomics, Antioxidant Capacity, and Total Phenolic Content of Honey produced by Apis mellifera in Guam and Okinawa 1. Project Overview Scientific rationale and importance: This is...",
        "created_by": User.objects.get(id=1),
        "goal_amount": 88000,  # Goal amount in USD or specified currency
        "goal_currency": USD,
        "status": Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
        "bounty_type": Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
        "bounty_amount": 1500,  # Bounty amount in RSC
        "expiration_date": datetime.now(pytz.UTC) - timedelta(days=30),
        "bounty_status": Bounty.EXPIRED,
        "amount_raised": 4000,
    },
]

for proposal in proposals:
    unified_document = ResearchhubUnifiedDocument.objects.create(
        document_type=PREREGISTRATION
    )

    hubs = Hub.objects.filter(id__in=[1, 2])  # Replace with actual hub IDs
    unified_document.hubs.add(*hubs)

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
    authors = Author.objects.filter(id__in=[1, 2])  # Replace with actual author IDs
    funding_post.authors.set(authors)

    # Creating the Associated Fundraise (Required for Funding Feed)
    # For RFP posts to appear in the funding feed, they need an associated Fundraise object:
    # Create a fundraise for the RFP to appear in funding feed
    fundraise_service = FundraiseService()
    fundraise = fundraise_service.create_fundraise_with_escrow(
        user=proposal["created_by"],
        unified_document=unified_document,
        goal_amount=proposal["goal_amount"],  # Goal amount in USD or specified currency
        goal_currency=USD,
        status=Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
    )

    fundraise.end_date = proposal["expiration_date"]
    fundraise.save(update_fields=["end_date"])

    # Creating the Associated Bounty (Optional)
    # RFP posts can also have an associated bounty to incentivize responses:
    # Create an escrow to hold the bounty funds
    escrow = Escrow.objects.create(
        created_by=proposal["created_by"],
        hold_type=Escrow.BOUNTY,
        amount_holding=proposal["bounty_amount"],  # Amount in RSC tokens
        object_id=funding_post.id,
        content_type=ContentType.objects.get_for_model(funding_post),
    )

    # Create the bounty
    expiration_date = proposal["expiration_date"]
    bounty = Bounty.objects.create(
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

# Prerequisites: Exchange Rate Setup
# Before creating posts with fundraises, ensure an exchange rate exists:
# Check if exchange rate exists, create if not
if not RscExchangeRate.objects.exists():
    RscExchangeRate.objects.create(
        price_source=MORALIS,
        rate=0.01,  # 1 RSC = $0.01 USD (adjust as needed)
    )


# # Assuming you have a user instance
# user1 = User.objects.get(id=1)  # Replace with desired user ID

# # Create the unified document first (required)
# # Use PREREGISTRATION to appear in funding feed
# unified_document = ResearchhubUnifiedDocument.objects.create(
#     document_type=PREREGISTRATION
# )

# # Optionally add hubs
# hubs = Hub.objects.filter(id__in=[1, 2])  # Replace with actual hub IDs
# unified_document.hubs.add(*hubs)


# # Create the RFP post
# title = "RFP: Development of Novel Machine Learning Algorithm for Climate Prediction"
# funding_post = ResearchhubPost.objects.create(
#     created_by=user1,
#     document_type=PREREGISTRATION,  # Use PREREGISTRATION to appear in funding feed
#     title=title,
#     slug=slugify(title),
#     renderable_text="<p>We are seeking proposals for the development of a novel machine learning algorithm capable of predicting climate patterns with high accuracy. The successful proposal will receive a bounty of 10,000 RSC tokens...</p>",
#     editor_type=CK_EDITOR,
#     unified_document=unified_document,
#     bounty_type="REVIEW",  # Can be REVIEW, ANSWER, or GENERIC_COMMENT for bounty behavior
#     doi=None,  # Optional: Add DOI if assigning one
#     image=None,  # Optional: Add image URL or file
#     preview_img=None,  # Optional: Add preview image
#     note_id=None,  # Optional: Link to a note if applicable
#     prev_version=None,  # For versioning
# )

# # Add authors (many-to-many relationship)
# authors = Author.objects.filter(id__in=[1, 2])  # Replace with actual author IDs
# funding_post.authors.set(authors)

# ## Creating the Associated Fundraise (Required for Funding Feed)

# # For RFP posts to appear in the funding feed, they need an associated Fundraise object:

# # Create a fundraise for the RFP to appear in funding feed
# fundraise_service = FundraiseService()
# fundraise = fundraise_service.create_fundraise_with_escrow(
#     user=user1,
#     unified_document=unified_document,
#     goal_amount=10000,  # Goal amount in USD or specified currency
#     goal_currency=USD,
#     status=Fundraise.OPEN,  # OPEN, CLOSED, or COMPLETED
# )

# # Creating the Associated Bounty (Optional)
# # RFP posts can also have an associated bounty to incentivize responses:
# # Create an escrow to hold the bounty funds
# escrow = Escrow.objects.create(
#     created_by=user1,
#     hold_type=Escrow.BOUNTY,
#     amount_holding=10000,  # Amount in RSC tokens
#     object_id=funding_post.id,
#     content_type=ContentType.objects.get_for_model(funding_post),
# )

# # Create the bounty
# expiration_date = datetime.now(pytz.UTC) + timedelta(days=30)  # 30 days from now
# bounty = Bounty.objects.create(
#     created_by=user1,
#     unified_document=unified_document,
#     item_content_type=ContentType.objects.get_for_model(funding_post),
#     item_object_id=funding_post.id,
#     bounty_type=Bounty.Type.REVIEW,  # REVIEW, ANSWER, or OTHER
#     amount=10000,  # Bounty amount in RSC
#     escrow=escrow,
#     expiration_date=expiration_date,
#     status=Bounty.OPEN,
#     parent=None,  # Set if this is a contribution to existing bounty
# )

# ## Prerequisites: Exchange Rate Setup

# # Before creating posts with fundraises, ensure an exchange rate exists:


# # Check if exchange rate exists, create if not
# if not RscExchangeRate.objects.exists():
#     RscExchangeRate.objects.create(
#         price_source=MORALIS,
#         rate=0.01,  # 1 RSC = $0.01 USD (adjust as needed)
#     )

print("funding seeded")

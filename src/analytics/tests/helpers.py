"""
Test helper functions for creating Personalize export test data.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.contrib.contenttypes.models import ContentType

from hub.models import Hub
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from personalize.config.constants import DELIMITER
from purchase.models import Fundraise, Grant, GrantApplication, Purchase
from reputation.models import Bounty, BountySolution, Escrow
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import DISCUSSION
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC_TYPE,
)
from researchhub_document.related_models.constants.document_type import (
    PAPER as PAPER_DOC_TYPE,
)
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    QUESTION,
)
from user.models import Author, User


def create_hub_with_namespace(name, namespace):
    """Create a hub with a specific namespace."""
    hub = Hub.objects.create(
        name=name,
        namespace=namespace,
        slug=f"{name.lower().replace(' ', '-')}-{namespace}",
    )
    return hub


def create_prefetched_paper(
    title="Test Paper",
    abstract="Test abstract",
    paper_publish_date=None,
    citations=0,
    external_metadata=None,
    user=None,
    hubs=None,
    authors=None,
):
    """
    Create a paper with all required prefetch relations.

    Returns the unified document with proper prefetch_related.
    """
    if paper_publish_date is None:
        paper_publish_date = datetime.now(pytz.UTC)

    if user is None:
        user = User.objects.create_user(
            username=f"testuser_{datetime.now().timestamp()}",
            email=f"test_{datetime.now().timestamp()}@example.com",
        )

    # Create paper
    paper = Paper.objects.create(
        title=title,
        paper_title=title,
        abstract=abstract,
        paper_publish_date=paper_publish_date,
        uploaded_by=user,
        citations=citations,
        external_metadata=external_metadata or {},
    )

    # Create unified document
    unified_doc = ResearchhubUnifiedDocument.objects.create(
        document_type=PAPER_DOC_TYPE,
        score=0,
    )
    paper.unified_document = unified_doc
    paper.save()

    # Add hubs
    if hubs:
        unified_doc.hubs.set(hubs)

    # Add authors
    if authors:
        for author in authors:
            Authorship.objects.create(
                paper=paper,
                author=author,
                author_position="first",
            )

    # Return with proper prefetch
    return (
        ResearchhubUnifiedDocument.objects.select_related(
            "paper",
        )
        .prefetch_related(
            "hubs",
            "related_bounties",
            "fundraises",
            "grants",
            "paper__authorships__author",
            "posts__authors",
        )
        .get(id=unified_doc.id)
    )


def create_prefetched_grant(
    title="Test Grant",
    amount=Decimal("50000.00"),
    status=Grant.OPEN,
    end_date=None,
    user=None,
    contacts=None,
    hubs=None,
):
    """
    Create a grant/RFP with contacts and all prefetch relations.

    Returns the unified document with proper prefetch_related.
    """
    if user is None:
        user = User.objects.create_user(
            username=f"grantuser_{datetime.now().timestamp()}",
            email=f"grant_{datetime.now().timestamp()}@example.com",
        )

    # Create grant post
    post = create_post(
        created_by=user,
        document_type=GRANT_DOC_TYPE,
        title=title,
    )

    # Create grant
    grant = Grant.objects.create(
        created_by=user,
        unified_document=post.unified_document,
        amount=amount,
        currency="USD",
        organization="Test Foundation",
        description="Test grant description",
        status=status,
        end_date=end_date,
    )

    # Add contacts
    if contacts:
        grant.contacts.set(contacts)

    # Add hubs
    if hubs:
        post.unified_document.hubs.set(hubs)

    # Return with proper prefetch
    return (
        ResearchhubUnifiedDocument.objects.select_related(
            "paper",
        )
        .prefetch_related(
            "hubs",
            "related_bounties",
            "fundraises",
            "grants",
            "paper__authorships__author",
            "posts__authors",
        )
        .get(id=post.unified_document.id)
    )


def create_prefetched_proposal(
    title="Test Proposal",
    status=Fundraise.OPEN,
    end_date=None,
    user=None,
    hubs=None,
):
    """
    Create a preregistration/fundraise with all prefetch relations.

    Returns the unified document with proper prefetch_related.
    """
    if user is None:
        user = User.objects.create_user(
            username=f"proposaluser_{datetime.now().timestamp()}",
            email=f"proposal_{datetime.now().timestamp()}@example.com",
        )

    # Create proposal post
    post = create_post(
        created_by=user,
        document_type=PREREGISTRATION,
        title=title,
    )

    # Create fundraise
    fundraise = Fundraise.objects.create(
        created_by=user,
        unified_document=post.unified_document,
        goal_amount=Decimal("10000.00"),
        goal_currency="USD",
        status=status,
        end_date=end_date,
    )

    # Add hubs
    if hubs:
        post.unified_document.hubs.set(hubs)

    # Return with proper prefetch
    return (
        ResearchhubUnifiedDocument.objects.select_related(
            "paper",
        )
        .prefetch_related(
            "hubs",
            "related_bounties",
            "fundraises",
            "grants",
            "paper__authorships__author",
            "posts__authors",
        )
        .get(id=post.unified_document.id)
    )


def create_prefetched_post(
    title="Test Post",
    renderable_text="Test content",
    document_type=DISCUSSION,
    user=None,
    authors=None,
    hubs=None,
):
    """
    Create a discussion/question post with all prefetch relations.

    Returns the unified document with proper prefetch_related.
    """
    if user is None:
        user = User.objects.create_user(
            username=f"postuser_{datetime.now().timestamp()}",
            email=f"post_{datetime.now().timestamp()}@example.com",
        )

    # Create post
    post = create_post(
        created_by=user,
        document_type=document_type,
        title=title,
        renderable_text=renderable_text,
    )

    # Add authors
    if authors:
        post.authors.set(authors)

    # Add hubs
    if hubs:
        post.unified_document.hubs.set(hubs)

    # Return with proper prefetch
    return (
        ResearchhubUnifiedDocument.objects.select_related(
            "paper",
        )
        .prefetch_related(
            "hubs",
            "related_bounties",
            "fundraises",
            "grants",
            "paper__authorships__author",
            "posts__authors",
        )
        .get(id=post.unified_document.id)
    )


def create_batch_data(
    has_active_bounty=False,
    has_solutions=False,
    proposal_is_open=False,
    proposal_has_funders=False,
    rfp_is_open=False,
    rfp_has_applicants=False,
):
    """Create batch data dictionaries for testing."""
    return {
        "bounty": {
            "has_active_bounty": has_active_bounty,
            "has_solutions": has_solutions,
        },
        "proposal": {
            "is_open": proposal_is_open,
            "has_funders": proposal_has_funders,
        },
        "rfp": {
            "is_open": rfp_is_open,
            "has_applicants": rfp_has_applicants,
        },
        "review_count": {},
    }


def create_author(first_name="John", last_name="Doe"):
    """Create an author for testing."""
    return Author.objects.create(
        first_name=first_name,
        last_name=last_name,
    )


def create_bounty_for_document(unified_doc, status=Bounty.OPEN, user=None):
    """Create a bounty attached to a unified document."""
    if user is None:
        user = User.objects.create_user(
            username=f"bountyuser_{datetime.now().timestamp()}",
            email=f"bounty_{datetime.now().timestamp()}@example.com",
        )

    content_type = ContentType.objects.get_for_model(unified_doc)

    escrow = Escrow.objects.create(
        created_by=user,
        amount_holding=Decimal("100.00"),
        content_type=content_type,
        object_id=unified_doc.id,
    )

    bounty = Bounty.objects.create(
        unified_document=unified_doc,
        item_content_type=content_type,
        item_object_id=unified_doc.id,
        amount=Decimal("100.00"),
        created_by=user,
        escrow=escrow,
        status=status,
    )

    return bounty


def create_bounty_solution(bounty, user=None):
    """Create a solution for a bounty."""
    if user is None:
        user = User.objects.create_user(
            username=f"solutionuser_{datetime.now().timestamp()}",
            email=f"solution_{datetime.now().timestamp()}@example.com",
        )

    content_type = ContentType.objects.get_for_model(bounty.unified_document)

    solution = BountySolution.objects.create(
        bounty=bounty,
        content_type=content_type,
        object_id=bounty.unified_document.id,
        created_by=user,
    )

    return solution


def create_grant_application(grant, user=None):
    """Create an application for a grant."""
    from researchhub_document.helpers import create_post
    from researchhub_document.related_models.constants.document_type import (
        PREREGISTRATION,
    )

    if user is None:
        user = User.objects.create_user(
            username=f"applicant_{datetime.now().timestamp()}",
            email=f"applicant_{datetime.now().timestamp()}@example.com",
        )

    # Create a preregistration post for the application
    prereg_post = create_post(
        created_by=user,
        document_type=PREREGISTRATION,
        title="Application Proposal",
    )

    application = GrantApplication.objects.create(
        grant=grant,
        preregistration_post=prereg_post,
        applicant=user,
    )

    return application


def create_fundraise_contribution(fundraise, user=None, amount=Decimal("100.00")):
    """Create a contribution to a fundraise."""
    if user is None:
        user = User.objects.create_user(
            username=f"contributor_{datetime.now().timestamp()}",
            email=f"contributor_{datetime.now().timestamp()}@example.com",
        )

    content_type = ContentType.objects.get_for_model(fundraise)

    escrow = Escrow.objects.create(
        created_by=user,
        amount_holding=amount,
        content_type=content_type,
        object_id=fundraise.id,
    )

    purchase = Purchase.objects.create(
        user=user,
        content_type=content_type,
        object_id=fundraise.id,
        purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
        amount=amount,
    )

    return purchase

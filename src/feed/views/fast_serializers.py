"""
Ultra-fast serializers that completely bypass Django REST Framework.
These build raw dictionaries directly from model instances for maximum performance.
"""
from django.core.files.storage import default_storage
from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_document.related_models.constants.document_type import GRANT, PREREGISTRATION


def serialize_author_fast(author_profile):
    """
    Serialize author profile to dict without DRF overhead.
    Returns None if author_profile is None.
    """
    if not author_profile:
        return None
    
    profile_image = None
    if hasattr(author_profile, 'profile_image') and author_profile.profile_image:
        try:
            profile_image = author_profile.profile_image.url
        except (AttributeError, ValueError):
            profile_image = None
    
    headline = None
    if isinstance(author_profile.headline, dict):
        headline = author_profile.headline.get('title')
    
    user_data = None
    user = getattr(author_profile, 'user', None)
    if user:
        user_data = {
            'id': user.id,
            'is_verified': user.is_verified,
        }
    
    return {
        'id': author_profile.id,
        'first_name': author_profile.first_name,
        'last_name': author_profile.last_name,
        'profile_image': profile_image,
        'headline': headline,
        'description': author_profile.description,
        'user': user_data,
    }


def serialize_hub_fast(hub):
    """Serialize hub to dict. Returns None if hub is None."""
    if not hub:
        return None
    return {
        'id': hub.id,
        'name': hub.name,
        'slug': hub.slug,
    }


def serialize_fundraise_fast(fundraise):
    """
    Serialize fundraise to dict without DRF overhead.
    Includes goal amounts, raised amounts, and contributor count.
    Returns None if fundraise is None.
    """
    if not fundraise:
        return None
    
    usd_goal = float(fundraise.goal_amount)
    rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
    
    usd_raised = rsc_raised = contributor_count = 0
    if fundraise.escrow_id:
        usd_raised = fundraise.get_amount_raised(currency=USD)
        rsc_raised = fundraise.get_amount_raised(currency=RSC)
        contributor_count = fundraise.purchases.values('user_id').distinct().count()
    
    return {
        'id': fundraise.id,
        'status': fundraise.status,
        'goal_currency': fundraise.goal_currency,
        'start_date': fundraise.start_date,
        'end_date': fundraise.end_date,
        'created_date': fundraise.created_date,
        'updated_date': fundraise.updated_date,
        'goal_amount': {'usd': usd_goal, 'rsc': rsc_goal},
        'amount_raised': {'usd': usd_raised, 'rsc': rsc_raised},
        'contributors': {'total': contributor_count, 'top': []},
    }


def serialize_grant_fast(grant):
    """
    Serialize grant to dict without DRF overhead.
    Includes amount conversion, creator, and applications.
    Returns None if grant is None.
    """
    if not grant:
        return None
    
    usd_amount = float(grant.amount)
    rsc_amount = RscExchangeRate.usd_to_rsc(usd_amount)
    
    created_by = None
    if grant.created_by and hasattr(grant.created_by, 'author_profile'):
        created_by = serialize_author_fast(grant.created_by.author_profile)
    
    applications = [
        {'applicant': serialize_author_fast(app.applicant.author_profile)}
        for app in grant.applications.all()
        if app.applicant and hasattr(app.applicant, 'author_profile')
    ]
    
    return {
        'id': grant.id,
        'status': grant.status,
        'currency': grant.currency,
        'organization': grant.organization,
        'description': grant.description,
        'start_date': grant.start_date,
        'end_date': grant.end_date,
        'is_expired': grant.is_expired(),
        'is_active': grant.is_active(),
        'amount': {
            'usd': usd_amount,
            'rsc': rsc_amount,
            'formatted': f'${usd_amount:,.0f}',
        },
        'created_by': created_by,
        'applications': applications,
    }


def serialize_post_fast(post):
    """
    Serialize post to dict without DRF overhead.
    Includes truncated text, hub, and related fundraise/grant.
    Returns None if post is None.
    """
    if not post:
        return None
    
    text = (post.renderable_text[:255] + '...') if len(post.renderable_text) > 255 else post.renderable_text
    image_url = default_storage.url(post.image) if post.image else None
    
    hub = None
    fundraise = None
    grant = None
    unified_doc_id = None
    
    if post.unified_document:
        unified_doc_id = post.unified_document.id
        primary_hub = post.unified_document.get_primary_hub(fallback=True)
        hub = serialize_hub_fast(primary_hub)
        
        if post.document_type == PREREGISTRATION:
            fundraises = post.unified_document.fundraises.all()
            if fundraises:
                fundraise = serialize_fundraise_fast(fundraises[0])
        
        elif post.document_type == GRANT:
            grants = post.unified_document.grants.all()
            if grants:
                grant = serialize_grant_fast(grants[0])
    
    return {
        'id': post.id,
        'created_date': post.created_date,
        'slug': post.slug,
        'title': post.title,
        'renderable_text': text,
        'type': post.document_type,
        'image_url': image_url,
        'unified_document_id': unified_doc_id,
        'hub': hub,
        'fundraise': fundraise,
        'grant': grant,
        'reviews': [],
    }


def serialize_feed_entry_fast(feed_entry, request=None):
    """
    Serialize feed entry to dict without DRF overhead.
    Includes content object, author, metrics, and user-specific data.
    """
    content_object = serialize_post_fast(feed_entry.item)
    
    author = None
    if feed_entry.item:
        created_by = getattr(feed_entry.item, 'created_by', None)
        if created_by and hasattr(created_by, 'author_profile'):
            author = serialize_author_fast(created_by.author_profile)
    
    metrics = {
        'votes': getattr(feed_entry.item, 'score', 0),
        'comments': getattr(feed_entry.item, 'discussion_count', 0),
    }
    
    is_nonprofit = False
    if feed_entry.unified_document and hasattr(feed_entry.unified_document, 'fundraises'):
        fundraises = feed_entry.unified_document.fundraises.all()
        if fundraises:
            is_nonprofit = fundraises[0].nonprofit_links.exists()
    
    user_vote = None
    if request and getattr(request.user, 'is_authenticated', False):
        vote = getattr(feed_entry.item, '_user_vote', None)
        if vote:
            user_vote = {
                'id': vote.id,
                'vote_type': vote.vote_type,
                'created_date': vote.created_date,
            }
    
    return {
        'id': feed_entry.id,
        'content_type': feed_entry.content_type.model.upper(),
        'content_object': content_object,
        'action': feed_entry.action,
        'action_date': feed_entry.action_date,
        'author': author,
        'metrics': metrics,
        'is_nonprofit': is_nonprofit,
        'user_vote': user_vote,
    }


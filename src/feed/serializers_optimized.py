"""
Optimized serializers for feed endpoints.
These serializers include ONLY the fields actually needed by the frontend,
avoiding expensive nested serializations and N+1 queries.
"""
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import default_storage
from rest_framework import serializers

from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_document.related_models.constants.document_type import GRANT, PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

from .models import FeedEntry


def serialize_author(author_profile):
    """Fast author serialization without DRF overhead"""
    if not author_profile:
        return None
    
    profile_image = None
    if hasattr(author_profile, 'profile_image') and author_profile.profile_image:
        try:
            profile_image = author_profile.profile_image.url
        except:
            pass
    
    headline = None
    if author_profile.headline and isinstance(author_profile.headline, dict):
        headline = author_profile.headline.get('title')
    
    user_data = None
    if hasattr(author_profile, 'user') and author_profile.user:
        user_data = {
            'id': author_profile.user.id,
            'is_verified': author_profile.user.is_verified,
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


class OptimizedAuthorSerializer(serializers.Serializer):
    """Minimal author serializer with only required fields"""
    id = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    profile_image = serializers.SerializerMethodField()
    headline = serializers.SerializerMethodField()
    description = serializers.CharField(allow_null=True)
    user = serializers.SerializerMethodField()

    def get_profile_image(self, obj):
        if hasattr(obj, 'profile_image') and obj.profile_image and obj.profile_image.name:
            return obj.profile_image.url
        return None

    def get_headline(self, obj):
        if obj.headline and isinstance(obj.headline, dict) and 'title' in obj.headline:
            return obj.headline.get('title')
        return None

    def get_user(self, obj):
        """Return minimal user data"""
        if hasattr(obj, 'user') and obj.user:
            return {
                'id': obj.user.id,
                'is_verified': obj.user.is_verified,
            }
        return None


def serialize_hub(hub):
    """Fast hub serialization without DRF overhead"""
    if not hub:
        return None
    return {
        'id': hub.id,
        'name': hub.name,
        'slug': hub.slug,
    }


class OptimizedHubSerializer(serializers.Serializer):
    """Minimal hub serializer"""
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.SlugField()


class OptimizedFundraiseSerializer(serializers.Serializer):
    """Optimized fundraise serializer - only essential fields"""
    id = serializers.IntegerField()
    status = serializers.CharField()
    goal_currency = serializers.CharField()
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField(allow_null=True)
    created_date = serializers.DateTimeField()
    updated_date = serializers.DateTimeField()
    
    goal_amount = serializers.SerializerMethodField()
    amount_raised = serializers.SerializerMethodField()
    contributors = serializers.SerializerMethodField()

    def get_goal_amount(self, obj):
        usd_goal = float(obj.goal_amount)
        rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
        return {
            'usd': usd_goal,
            'rsc': rsc_goal,
        }

    def get_amount_raised(self, obj):
        """Only compute if escrow exists, avoid method call overhead"""
        if not obj.escrow_id:
            return {'usd': 0, 'rsc': 0}
        
        usd = obj.get_amount_raised(currency=USD)
        rsc = obj.get_amount_raised(currency=RSC)
        return {'usd': usd, 'rsc': rsc}

    def get_contributors(self, obj):
        """Return minimal contributor data - defer full list to detail endpoint"""
        # Only return total count in list view
        # Frontend can fetch full contributor list when needed
        if not obj.escrow_id:
            return {'total': 0, 'top': []}
        
        # Get count of unique contributors without fetching all data
        contributor_count = obj.purchases.values('user_id').distinct().count()
        
        # Optionally return top 3 contributors only
        top_contributors = []
        if self.context.get('include_top_contributors', False):
            top_purchases = obj.purchases.select_related(
                'user', 'user__author_profile'
            ).order_by('-amount')[:3]
            
            for purchase in top_purchases:
                if purchase.user and hasattr(purchase.user, 'author_profile'):
                    top_contributors.append({
                        'id': purchase.user.id,
                        'author_profile': serialize_author(purchase.user.author_profile),
                        'total_contribution': float(purchase.amount),
                    })
        
        return {
            'total': contributor_count,
            'top': top_contributors,
        }


class OptimizedGrantSerializer(serializers.Serializer):
    """Optimized grant serializer - only essential fields"""
    id = serializers.IntegerField()
    status = serializers.CharField()
    currency = serializers.CharField()
    organization = serializers.CharField()
    description = serializers.CharField()
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField(allow_null=True)
    is_expired = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    
    amount = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    applications = serializers.SerializerMethodField()

    def get_is_expired(self, obj):
        return obj.is_expired()

    def get_is_active(self, obj):
        return obj.is_active()

    def get_amount(self, obj):
        usd_amount = float(obj.amount)
        rsc_amount = RscExchangeRate.usd_to_rsc(usd_amount)
        return {
            'usd': usd_amount,
            'rsc': rsc_amount,
            'formatted': f'${usd_amount:,.0f}',
        }

    def get_created_by(self, obj):
        if obj.created_by and hasattr(obj.created_by, 'author_profile'):
            return serialize_author(obj.created_by.author_profile)
        return None

    def get_applications(self, obj):
        """Return minimal application data - uses prefetched applications"""
        # Access prefetched applications (already loaded with select_related in view)
        applications = obj.applications.all()
        
        return [
            {
                'applicant': serialize_author(app.applicant.author_profile)
                if app.applicant and hasattr(app.applicant, 'author_profile') else None
            }
            for app in applications
        ]


class OptimizedPostSerializer(serializers.Serializer):
    """Optimized post serializer for feed items"""
    id = serializers.IntegerField()
    created_date = serializers.DateTimeField()
    slug = serializers.SlugField()
    title = serializers.CharField()
    renderable_text = serializers.SerializerMethodField()
    type = serializers.CharField(source='document_type')
    image_url = serializers.SerializerMethodField()
    unified_document_id = serializers.IntegerField(source='unified_document.id')
    
    # Related objects
    hub = serializers.SerializerMethodField()
    fundraise = serializers.SerializerMethodField()
    grant = serializers.SerializerMethodField()

    def get_renderable_text(self, obj):
        """Truncate text to save bandwidth"""
        text = obj.renderable_text[:255]
        if len(obj.renderable_text) > 255:
            text += '...'
        return text

    def get_image_url(self, obj):
        if not obj.image:
            return None
        return default_storage.url(obj.image)

    def get_hub(self, obj):
        """Get primary hub from prefetched data"""
        if obj.unified_document:
            # This should use prefetched hubs to avoid extra query
            hub = obj.unified_document.get_primary_hub(fallback=True)
            return serialize_hub(hub)
        return None

    def get_fundraise(self, obj):
        """Return fundraise data if exists - uses prefetched data"""
        if obj.document_type == PREREGISTRATION and obj.unified_document:
            # Access prefetched fundraises
            fundraises = obj.unified_document.fundraises.all()
            if fundraises:
                return OptimizedFundraiseSerializer(
                    fundraises[0], 
                    context=self.context
                ).data
        return None

    def get_grant(self, obj):
        """Return grant data if exists - uses prefetched data"""
        if obj.document_type == GRANT and obj.unified_document:
            # Access prefetched grants
            grants = obj.unified_document.grants.all()
            if grants:
                return OptimizedGrantSerializer(
                    grants[0],
                    context=self.context
                ).data
        return None


class OptimizedFundingFeedEntrySerializer(serializers.Serializer):
    """Optimized feed entry serializer for funding feed"""
    id = serializers.IntegerField()
    content_type = serializers.SerializerMethodField()
    content_object = serializers.SerializerMethodField()
    action = serializers.CharField()
    action_date = serializers.DateTimeField()
    author = serializers.SerializerMethodField()
    metrics = serializers.SerializerMethodField()
    is_nonprofit = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()

    def get_content_type(self, obj):
        return obj.content_type.model.upper()

    def get_content_object(self, obj):
        """Serialize the post using optimized serializer"""
        return OptimizedPostSerializer(obj.item, context=self.context).data

    def get_author(self, obj):
        """Return author from the post's created_by field"""
        if obj.item and hasattr(obj.item, 'created_by') and obj.item.created_by:
            if hasattr(obj.item.created_by, 'author_profile'):
                return serialize_author(obj.item.created_by.author_profile)
        return None

    def get_metrics(self, obj):
        """Return vote and comment counts"""
        metrics = {}
        if hasattr(obj.item, 'score'):
            metrics['votes'] = obj.item.score
        if hasattr(obj.item, 'unified_document') and obj.item.unified_document:
            # Use prefetched discussion count if available
            if hasattr(obj.item.unified_document, '_discussion_count'):
                metrics['comments'] = obj.item.unified_document._discussion_count
            else:
                # Fallback to discussion_count field
                metrics['comments'] = getattr(obj.item, 'discussion_count', 0)
        return metrics

    def get_is_nonprofit(self, obj):
        """Check if fundraise is linked to nonprofit"""
        if obj.unified_document and hasattr(obj.unified_document, 'fundraises'):
            fundraises = obj.unified_document.fundraises.all()
            if fundraises:
                # Use prefetched nonprofit_links if available
                return fundraises[0].nonprofit_links.exists()
        return False

    def get_user_vote(self, obj):
        """Return user's vote if authenticated"""
        user = self.context.get('request', {}).user if isinstance(self.context.get('request', {}), object) else None
        if not user or not user.is_authenticated:
            return None
        
        # This should be added via annotation in the view for efficiency
        if hasattr(obj.item, '_user_vote'):
            vote = obj.item._user_vote
            if vote:
                return {
                    'id': vote.id,
                    'vote_type': vote.vote_type,
                    'created_date': vote.created_date,
                }
        return None


class OptimizedGrantFeedEntrySerializer(OptimizedFundingFeedEntrySerializer):
    """Optimized feed entry serializer for grant feed - inherits from funding"""
    # Grants don't need is_nonprofit field
    pass


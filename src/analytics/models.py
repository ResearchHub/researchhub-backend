from django.db import models

from user.models import User

INTERACTIONS = {
    "CLICK": "CLICK",
    "VIEW": "VIEW",
}

INTERACTION_CHOICES = [
    (INTERACTIONS["CLICK"], INTERACTIONS["CLICK"]),
    (INTERACTIONS["VIEW"], INTERACTIONS["VIEW"]),
]


class WebsiteVisits(models.Model):
    uuid = models.CharField(max_length=36)
    saw_signup_banner = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.uuid}"


# TODO: Future database models for ML/Personalize integration
# 
# The following models should be added when implementing database storage
# for user interactions and recommendations:
#
# class UserInteraction(models.Model):
#     """
#     Stores user interactions with content for ML/recommendations.
#     
#     Tracks positive and negative signals:
#     - Positive: clicks, upvotes, shares, downloads, fundraises
#     - Negative: downvotes, flags, hides
#     
#     Each interaction has a weight that indicates its importance
#     for understanding user preferences.
#     """
#     user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ml_interactions', db_index=True)
#     item_id = models.CharField(max_length=255, db_index=True, help_text="ID of the item (usually unified_document_id)")
#     item_type = models.CharField(max_length=50, default='document', help_text="Type of item (document, paper, post, etc.)")
#     event_type = models.CharField(max_length=50, db_index=True, help_text="Type of interaction (click, upvote, share, etc.)")
#     weight = models.FloatField(default=1.0, help_text="Weight/importance of this interaction")
#     timestamp = models.DateTimeField(db_index=True, help_text="When the interaction occurred")
#     metadata = models.JSONField(default=dict, blank=True, help_text="Additional event properties from Amplitude")
#     sent_to_personalize = models.BooleanField(default=False, help_text="Whether this event was sent to AWS Personalize")
#     created_date = models.DateTimeField(auto_now_add=True)
#     updated_date = models.DateTimeField(auto_now=True)
#     
#     class Meta:
#         indexes = [
#             models.Index(fields=['user', 'timestamp']),
#             models.Index(fields=['item_id', 'timestamp']),
#             models.Index(fields=['event_type', 'timestamp']),
#         ]
#         ordering = ['-timestamp']
#
# class ImpressionEvent(models.Model):
#     """
#     Stores impression events - items that were shown to users.
#     
#     This is VERY important for ML because it helps the system understand
#     negative signals (items the user saw but didn't interact with).
#     
#     Two types of impressions:
#     - initial_impression: Items loaded in feed (user might not have seen all)
#     - scroll_impression: Items user scrolled to (definite view)
#     """
#     user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ml_impressions', db_index=True)
#     event_type = models.CharField(max_length=50, choices=[
#         ('initial_impression', 'Initial Impression'),
#         ('scroll_impression', 'Scroll Impression'),
#     ], help_text="Type of impression")
#     items_shown = ArrayField(models.CharField(max_length=255), help_text="List of item IDs that were shown")
#     weight = models.FloatField(default=0.3, help_text="Weight of this impression type")
#     timestamp = models.DateTimeField(db_index=True, help_text="When the impression occurred")
#     metadata = models.JSONField(default=dict, blank=True, help_text="Additional event properties")
#     sent_to_personalize = models.BooleanField(default=False, help_text="Whether this event was sent to AWS Personalize")
#     created_date = models.DateTimeField(auto_now_add=True)
#     updated_date = models.DateTimeField(auto_now=True)
#     
#     class Meta:
#         indexes = [
#             models.Index(fields=['user', 'timestamp']),
#             models.Index(fields=['event_type', 'timestamp']),
#         ]
#         ordering = ['-timestamp']
#
# class PersonalizeRecommendation(models.Model):
#     """
#     Caches recommendations from AWS Personalize to avoid excessive API calls.
#     
#     Recommendations are refreshed periodically or when user activity changes significantly.
#     """
#     user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='personalize_recommendations', db_index=True)
#     recommended_items = models.JSONField(help_text="List of recommended item IDs with scores")
#     algorithm_version = models.CharField(max_length=50, default='1.0', help_text="Version of recommendation algorithm")
#     expires_at = models.DateTimeField(db_index=True, help_text="When these recommendations expire")
#     created_date = models.DateTimeField(auto_now_add=True)
#     updated_date = models.DateTimeField(auto_now=True)
#     
#     class Meta:
#         indexes = [
#             models.Index(fields=['user', 'expires_at']),
#         ]
#         ordering = ['-created_date']

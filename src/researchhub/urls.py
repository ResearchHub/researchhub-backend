"""researchhub URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework import routers

import analytics.views
import bullet_point.views
import debug_toolbar
import discussion.views
import google_analytics.views
import hub.views
import hypothesis.views as hypothesis_views
import invite.views as invite_views
import mailing_list.views
import new_feature_release.views
import note.views as note_views
import notification.views
import oauth.urls
import oauth.views
import paper.views
import purchase.views
import reputation.views
import researchhub_case.views as researchhub_case_views
import researchhub_document.views as researchhub_document_views
import researchhub.views
import search.urls
import summary.views
import user.views

from user.views import GatekeeperViewSet

from researchhub.settings import USE_DEBUG_TOOLBAR, INSTALLED_APPS

router = routers.DefaultRouter()

router.register(
    r'new_feature_release',
    new_feature_release.views.NewFeatureViewSet,
    basename='new_feature_release',
)

# NOTE: calvinhlee - the way coments are handled is very inefficient. We need to refactor this
router.register(
    r'paper/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply',
    discussion.views.ReplyViewSet,
    basename='discussion_thread_comment_replies'
)

router.register(
    r'paper/([0-9]+)/discussion/([0-9]+)/comment',
    discussion.views.CommentViewSet,
    basename='discussion_thread_comments'
)

router.register(
    r'paper/([0-9]+)/discussion',
    discussion.views.ThreadViewSet,
    basename='discussion_threads'
)

router.register(
    r'post/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply',
    discussion.views.ReplyViewSet,
    basename='post_discussion_thread_comment_replies'
)

router.register(
    r'post/([0-9]+)/discussion/([0-9]+)/comment',
    discussion.views.CommentViewSet,
    basename='post_discussion_thread_comments'
)

router.register(
    r'post/([0-9]+)/discussion',
    discussion.views.ThreadViewSet,
    basename='post_discussion_threads'
)

router.register(
    r'hypothesis/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply',
    discussion.views.ReplyViewSet,
    basename='hypothesis_discussion_thread_comment_replies'
)

router.register(
    r'hypothesis/([0-9]+)/discussion/([0-9]+)/comment',
    discussion.views.CommentViewSet,
    basename='hypothesis_discussion_thread_comments'
)

router.register(
    r'hypothesis/([0-9]+)/discussion',
    discussion.views.ThreadViewSet,
    basename='hypothesis_discussion_threads'
)

router.register(
    r'citation/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply',
    discussion.views.ReplyViewSet,
    basename='citation_discussion_thread_comment_replies'
)

router.register(
    r'citation/([0-9]+)/discussion/([0-9]+)/comment',
    discussion.views.CommentViewSet,
    basename='citation_discussion_thread_comments'
)

router.register(
    r'citation/([0-9]+)/discussion',
    discussion.views.ThreadViewSet,
    basename='citation_discussion_threads'
)


router.register(
    r'paper/discussion/file',
    discussion.views.CommentFileUpload,
    basename='discussion_file_upload'
)


router.register(
    r'paper/([0-9]+)/bullet_point',
    bullet_point.views.BulletPointViewSet,
    basename='bullet_points'
)

router.register(
    r'paper/featured_papers',
    paper.views.FeaturedPaperViewSet,
    basename='featured_papers'
)

router.register(
    r'paper/([0-9]+)/additional_file',
    paper.views.AdditionalFileViewSet,
    basename='additional_files'
)

router.register(
    r'paper',
    paper.views.PaperViewSet,
    basename='paper'
)

router.register(
    r'author',
    user.views.AuthorViewSet,
    basename='author'
)

router.register(
    r'bullet_point',
    bullet_point.views.BulletPointViewSet,
    basename='bullet_point'
)

router.register(
    r'summary',
    summary.views.SummaryViewSet,
    basename='summary'
)

router.register(
    r'hub',
    hub.views.HubViewSet,
    basename='hub'
)

router.register(
    r'hub_category',
    hub.views.HubCategoryViewSet,
    basename='hub_category'
)

router.register(
    r'university',
    user.views.UniversityViewSet,
    basename='university'
)

router.register(
    r'major',
    user.views.MajorViewSet,
    basename='major'
)

router.register(
    r'organization',
    user.views.OrganizationViewSet,
    basename='organization'
)

router.register(
    r'email_recipient',
    mailing_list.views.EmailRecipientViewSet,
    basename='email_recipient'
)

router.register(
    r'notification',
    notification.views.NotificationViewSet,
    basename='notification'
)

router.register(
    r'figure',
    paper.views.FigureViewSet,
    basename='figure'
)

router.register(
    r'analytics/websiteviews',
    analytics.views.WebsiteVisitsViewSet,
    basename='websiteviews'
)

router.register(
    r'events/paper',
    analytics.views.PaperEventViewSet,
    basename='events_paper'
)

router.register(
    r'events/amplitude/forward_event',
    analytics.views.AmplitudeViewSet,
    basename='events_amplitude'
)

router.register(
    r'purchase',
    purchase.views.PurchaseViewSet,
    basename='purchase'
)

router.register(
    r'support',
    purchase.views.SupportViewSet,
    basename='support'
)

router.register(
    r'stripe',
    purchase.views.StripeViewSet,
    basename='stripe'
)

router.register(r'user', user.views.UserViewSet)

router.register(r'withdrawal', reputation.views.WithdrawalViewSet)

router.register(r'deposit', reputation.views.DepositViewSet)

router.register(r'user_verification', user.views.VerificationViewSet)

router.register(
    r'author_claim_case',
    researchhub_case_views.AuthorClaimCaseViewSet,
    basename='author_claim_case'
)

router.register(
    r'researchhub_posts',
    researchhub_document_views.ResearchhubPostViewSet,
    basename='researchhub_posts'
)

router.register(
    r'researchhub_unified_documents',
    researchhub_document_views.ResearchhubUnifiedDocumentViewSet,
    basename='researchhub_unified_documents',
)

router.register(
    r'hypothesis',
    hypothesis_views.HypothesisViewSet,
    basename='hypothesis'
)

router.register(
    r'citation',
    hypothesis_views.CitationViewSet,
    basename='citations'
)

router.register(
    r'note',
    note_views.NoteViewSet,
    basename='notes'
)

router.register(
    r'note_content',
    note_views.NoteContentViewSet,
    basename='note_content'
)

router.register(
    r'note_template',
    note_views.NoteTemplateViewSet,
    basename='note_template'
)

router.register(
    r'invite/organization',
    invite_views.OrganizationInvitationViewSet,
    basename='organization_invite'
)

router.register(
    r'invite/note',
    invite_views.NoteInvitationViewSet,
    basename='note_invite'
)

router.register(
    r'gatekeeper',
    GatekeeperViewSet,
    basename='gatekeeper'
)

urlpatterns = [
    path('admin/', admin.site.urls),
    re_path(r'^api/', include(router.urls)),
    path('api/events/forward_event/', google_analytics.views.forward_event),
    path(
        'api/author_claim_token_validation/',
        researchhub_case_views.validate_user_request_email
    ),
    path(
        'api/moderators/author_claim_case/',
        researchhub_case_views.handle_author_claim_cases_for_mods
    ),
    path(
        'api/moderators/author_claim_case/counts/',
        researchhub_case_views.get_author_claim_counts_for_mods
    ),
    path(
        'api/permissions/',
        researchhub.views.permissions,
        name='permissions'
    ),
    path('api/search/', include(search.urls)),
    path(
        'api/auth/orcid/connect/',
        oauth.views.orcid_connect,
        name='orcid_login'
    ),
    path(
        'api/auth/orcid/login/callback/',
        oauth.views.orcid_callback,
        name='orcid_callback'
    ),
    path(
        'auth/google/yolo/callback/',
        oauth.views.google_yolo_callback,
        name='google_yolo_callback'
    ),
    path(
        'api/auth/google/yolo/',
        oauth.views.GoogleYoloLogin.as_view(),
        name='google_yolo'
    ),
    path(
        'auth/google/login/callback/',
        oauth.views.google_callback,
        name='google_callback'
    ),
    path(
        'api/auth/captcha_verify/',
        oauth.views.captcha_verify,
        name='captcha_verify'
    ),
    path(
        'api/auth/google/login/',
        oauth.views.GoogleLogin.as_view(),
        name='google_login'
    ),
    path(r'api/auth/', include('rest_auth.urls')),
    re_path(r'^auth/signup/', include(oauth.urls.registration_urls)),
    re_path(r'^auth/', include(oauth.urls.default_urls)),
    path(
        'api/ckeditor/webhook/document_removed/',
        note_views.note_view.ckeditor_webhook_document_removed
    ),
    path('api/ckeditor/token/', note_views.note_view.ckeditor_token),
    path('email_notifications/', mailing_list.views.email_notifications),
    path('health/', researchhub.views.healthcheck),
    path('', researchhub.views.index, name='index'),
]

if 'silk' in INSTALLED_APPS:
    urlpatterns = [
        path('silk/', include('silk.urls', namespace='silk')),
    ] + urlpatterns

if USE_DEBUG_TOOLBAR:
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]

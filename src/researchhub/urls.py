"""researchhub URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""
import debug_toolbar
from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework import routers

import analytics.views
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
import paper.views as paper_views
import purchase.views
import reputation.views
import researchhub.views
import researchhub_case.views as researchhub_case_views
import researchhub_document.views as researchhub_document_views
import search.urls
import summary.views
import user.views
from peer_review.views import (
    PeerReviewInviteViewSet,
    PeerReviewRequestViewSet,
    PeerReviewViewSet,
)
from researchhub.settings import INSTALLED_APPS, USE_DEBUG_TOOLBAR
from review.views.review_view import ReviewViewSet
from user.views import editor_views

router = routers.DefaultRouter()

router.register(
    r"new_feature_release",
    new_feature_release.views.NewFeatureViewSet,
    basename="new_feature_release",
)

# NOTE: calvinhlee - the way coments are handled is very inefficient. We need to refactor this

router.register(r"discussion", discussion.views.ThreadViewSet, basename="discussion")
router.register(
    r"paper/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply",
    discussion.views.ReplyViewSet,
    basename="discussion_thread_comment_replies",
)

router.register(
    r"paper/([0-9]+)/discussion/([0-9]+)/comment",
    discussion.views.CommentViewSet,
    basename="discussion_thread_comments",
)

router.register(
    r"paper/([0-9]+)/discussion",
    discussion.views.ThreadViewSet,
    basename="discussion_threads",
)

router.register(
    r"researchhub_post/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply",
    discussion.views.ReplyViewSet,
    basename="post_discussion_thread_comment_replies",
)

router.register(
    r"researchhub_post/([0-9]+)/discussion/([0-9]+)/comment",
    discussion.views.CommentViewSet,
    basename="post_discussion_thread_comments",
)

router.register(
    r"researchhub_post/([0-9]+)/discussion",
    discussion.views.ThreadViewSet,
    basename="post_discussion_threads",
)

router.register(
    r"hypothesis/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply",
    discussion.views.ReplyViewSet,
    basename="hypothesis_discussion_thread_comment_replies",
)

router.register(
    r"hypothesis/([0-9]+)/discussion/([0-9]+)/comment",
    discussion.views.CommentViewSet,
    basename="hypothesis_discussion_thread_comments",
)

router.register(
    r"hypothesis/([0-9]+)/discussion",
    discussion.views.ThreadViewSet,
    basename="hypothesis_discussion_threads",
)

router.register(
    r"citation/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply",
    discussion.views.ReplyViewSet,
    basename="citation_discussion_thread_comment_replies",
)

router.register(
    r"citation/([0-9]+)/discussion/([0-9]+)/comment",
    discussion.views.CommentViewSet,
    basename="citation_discussion_thread_comments",
)

router.register(
    r"citation/([0-9]+)/discussion",
    discussion.views.ThreadViewSet,
    basename="citation_discussion_threads",
)

router.register(
    r"peer_review/([0-9]+)/discussion/([0-9]+)/comment/([0-9]+)/reply",
    discussion.views.ReplyViewSet,
    basename="post_discussion_thread_comment_replies",
)

router.register(
    r"peer_review/([0-9]+)/discussion/([0-9]+)/comment",
    discussion.views.CommentViewSet,
    basename="post_discussion_thread_comments",
)

router.register(
    r"peer_review/([0-9]+)/discussion",
    discussion.views.ThreadViewSet,
    basename="post_discussion_threads",
)


router.register(
    r"paper/discussion/file",
    discussion.views.CommentFileUpload,
    basename="discussion_file_upload",
)

router.register(
    r"paper/([0-9]+)/additional_file",
    paper_views.AdditionalFileViewSet,
    basename="additional_files",
)

router.register(
    r"paper/async_paper_updator",
    paper_views.AsyncPaperUpdatorViewSet,
    "async_paper_updator",
)

router.register(r"paper", paper_views.PaperViewSet, basename="paper")

router.register(
    r"paper_submission",
    paper_views.PaperSubmissionViewSet,
    basename="paper_submission",
)

router.register(r"author", user.views.AuthorViewSet, basename="author")

router.register(r"summary", summary.views.SummaryViewSet, basename="summary")

router.register(r"hub", hub.views.HubViewSet, basename="hub")

router.register(r"hub_category", hub.views.HubCategoryViewSet, basename="hub_category")

router.register(r"university", user.views.UniversityViewSet, basename="university")

router.register(r"major", user.views.MajorViewSet, basename="major")

router.register(
    r"organization", user.views.OrganizationViewSet, basename="organization"
)

router.register(r"audit", user.views.AuditViewSet, basename="audit")

router.register(
    r"contribution", user.views.ContributionViewSet, basename="contribution"
)

router.register(
    r"email_recipient",
    mailing_list.views.EmailRecipientViewSet,
    basename="email_recipient",
)

router.register(
    r"notification", notification.views.NotificationViewSet, basename="notification"
)

router.register(r"figure", paper_views.FigureViewSet, basename="figure")

router.register(
    r"analytics/websiteviews",
    analytics.views.WebsiteVisitsViewSet,
    basename="websiteviews",
)

router.register(
    r"events/paper", analytics.views.PaperEventViewSet, basename="events_paper"
)

router.register(
    r"events/amplitude/forward_event",
    analytics.views.AmplitudeViewSet,
    basename="events_amplitude",
)

router.register(r"purchase", purchase.views.PurchaseViewSet, basename="purchase")


# Deprecated endpoints

# router.register(
#     r'support',
#     purchase.views.SupportViewSet,
#     basename='support'
# )

# router.register(
#     r'stripe',
#     purchase.views.StripeViewSet,
#     basename='stripe'
# )

router.register(r"transactions", purchase.views.BalanceViewSet, basename="transactions")

router.register(r"user", user.views.UserViewSet)

router.register(r"withdrawal", reputation.views.WithdrawalViewSet)

router.register(r"deposit", reputation.views.DepositViewSet)

router.register(r"bounty", reputation.views.BountyViewSet)

router.register(r"user_verification", user.views.VerificationViewSet)

router.register(
    r"author_claim_case",
    researchhub_case_views.AuthorClaimCaseViewSet,
    basename="author_claim_case",
)

router.register(
    r"external_author_claim_case",
    researchhub_case_views.ExternalAuthorClaimCaseViewSet,
    basename="external_author_claim_case",
)

router.register(
    r"researchhub_post",
    researchhub_document_views.ResearchhubPostViewSet,
    basename="researchhub_post",
)

router.register(
    r"researchhub_unified_document",
    researchhub_document_views.ResearchhubUnifiedDocumentViewSet,
    basename="researchhub_unified_document",
)

router.register(
    r"hypothesis", hypothesis_views.HypothesisViewSet, basename="hypothesis"
)

router.register(r"citation", hypothesis_views.CitationViewSet, basename="citations")

router.register(r"note", note_views.NoteViewSet, basename="notes")

router.register(r"note_content", note_views.NoteContentViewSet, basename="note_content")

router.register(
    r"note_template", note_views.NoteTemplateViewSet, basename="note_template"
)

router.register(
    r"invite/organization",
    invite_views.OrganizationInvitationViewSet,
    basename="organization_invite",
)

router.register(
    r"invite/note", invite_views.NoteInvitationViewSet, basename="note_invite"
)

router.register(r"gatekeeper", user.views.GatekeeperViewSet, basename="gatekeeper")

router.register(
    r"user_external_token", user.views.UserApiTokenViewSet, basename="user_api_token"
)

router.register(r"peer_review", PeerReviewViewSet, basename="peer_review")

router.register(
    r"peer_review_requests", PeerReviewRequestViewSet, basename="peer_review_requests"
)

router.register(
    r"peer_review_invites", PeerReviewInviteViewSet, basename="peer_review_invites"
)

router.register(
    r"researchhub_unified_document/([0-9]+)/review", ReviewViewSet, basename="review"
)

urlpatterns = [
    path("admin/", admin.site.urls),
    re_path(r"^api/", include(router.urls)),
    path("api/events/forward_event/", google_analytics.views.forward_event),
    # TODO: calvinhlee - consolidate all mod views into 1 set
    path("api/get_hub_active_contributors/", editor_views.get_hub_active_contributors),
    path(
        "api/moderators/get_editors_by_contributions/",
        editor_views.get_editors_by_contributions,
    ),
    path("api/reputation/distribute_rsc/", reputation.views.distribute_rsc),
    path(
        "api/rsc/get_rsc_circulating_supply",
        reputation.views.get_rsc_circulating_supply,
    ),
    path("api/permissions/", researchhub.views.permissions, name="permissions"),
    path("api/search/", include(search.urls)),
    path("api/auth/orcid/connect/", oauth.views.orcid_connect, name="orcid_login"),
    path(
        "api/auth/orcid/login/callback/",
        oauth.views.orcid_callback,
        name="orcid_callback",
    ),
    path(
        "auth/google/yolo/callback/",
        oauth.views.google_yolo_callback,
        name="google_yolo_callback",
    ),
    path(
        "api/auth/google/yolo/",
        oauth.views.GoogleYoloLogin.as_view(),
        name="google_yolo",
    ),
    path(
        "auth/google/login/callback/",
        oauth.views.google_callback,
        name="google_callback",
    ),
    path("api/auth/captcha_verify/", oauth.views.captcha_verify, name="captcha_verify"),
    path(
        "api/auth/google/login/", oauth.views.GoogleLogin.as_view(), name="google_login"
    ),
    path(r"api/auth/", include("dj_rest_auth.urls")),
    re_path(r"^auth/signup/", include(oauth.urls.registration_urls)),
    re_path(r"^auth/", include(oauth.urls.default_urls)),
    path(
        "api/ckeditor/webhook/document_removed/",
        note_views.note_view.ckeditor_webhook_document_removed,
    ),
    path("api/ckeditor/token/", note_views.note_view.ckeditor_token),
    path("email_notifications/", mailing_list.views.email_notifications),
    path("health/", researchhub.views.healthcheck),
    path("", researchhub.views.index, name="index"),
]

if "silk" in INSTALLED_APPS:
    urlpatterns = [
        path("silk/", include("silk.urls", namespace="silk")),
    ] + urlpatterns

if USE_DEBUG_TOOLBAR:
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]

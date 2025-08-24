"""researchhub URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""

import debug_toolbar
from dj_rest_auth.views import (
    LogoutView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetView,
)
from django.conf import settings
from django.urls import include, path, re_path
from rest_framework import routers

import analytics.views
import discussion.views
import hub.views
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
import user.views
from feed.views import (
    FeedV2ViewSet,
    FeedViewSet,
    FundingFeedViewSet,
    GrantFeedViewSet,
    JournalFeedViewSet,
)
from organizations.views import NonprofitFundraiseLinkViewSet, NonprofitOrgViewSet
from paper.views import paper_upload_views
from purchase.views import stripe_webhook_view
from researchhub.views import asset_upload_view
from researchhub_comment.views.rh_comment_view import RhCommentViewSet
from review.views.peer_review_view import PeerReviewViewSet
from review.views.review_view import ReviewViewSet
from user.views import (
    author_views,
    editor_views,
    moderator_view,
    persona_webhook_view,
    sift_webhook_view,
)
from user.views.custom_verify_email_view import CustomVerifyEmailView
from user_saved.views import UserSavedView

router = routers.DefaultRouter()

router.register(
    r"paper/discussion/file",
    discussion.views.CommentFileUpload,
    basename="discussion_file_upload",
)

router.register(
    r"new_feature_release",
    new_feature_release.views.NewFeatureViewSet,
    basename="new_feature_release",
)

router.register(r"paper", paper_views.PaperViewSet, basename="paper")

router.register(
    r"paper_submission",
    paper_views.PaperSubmissionViewSet,
    basename="paper_submission",
)

router.register(r"author", author_views.AuthorViewSet, basename="author")

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

router.register(r"leaderboard", user.views.LeaderboardViewSet, basename="leaderboard")

router.register(
    r"payment/coinbase", purchase.views.CoinbaseViewSet, basename="coinbase"
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

router.register(r"purchase", purchase.views.PurchaseViewSet, basename="purchase")

router.register(r"transactions", purchase.views.BalanceViewSet, basename="transactions")

router.register(r"user", user.views.UserViewSet)

router.register(r"withdrawal", reputation.views.WithdrawalViewSet)

router.register(r"deposit", reputation.views.DepositViewSet)

router.register(r"bounty", reputation.views.BountyViewSet)

router.register(r"moderator", moderator_view.ModeratorView, basename="moderator")

router.register(
    r"author_claim_case",
    researchhub_case_views.AuthorClaimCaseViewSet,
    basename="author_claim_case",
)

router.register(
    r"researchhubpost",
    researchhub_document_views.ResearchhubPostViewSet,
    basename="researchhubpost",
)

router.register(
    r"researchhub_unified_document",
    researchhub_document_views.ResearchhubUnifiedDocumentViewSet,
    basename="researchhub_unified_document",
)

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

router.register(
    r"researchhub_unified_document/([0-9]+)/review", ReviewViewSet, basename="review"
)

router.register(
    r"paper/(?P<paper_id>\d+)/peer-review",
    PeerReviewViewSet,
    basename="peer_review",
)

router.register(
    r"exchange_rate", purchase.views.RscExchangeRateViewSet, basename="exchange_rate"
)
router.register(
    r"(?P<model>\w+)/(?P<model_object_id>[0-9]+)/comments",
    RhCommentViewSet,
    basename="rh_comments",
)

router.register(r"fundraise", purchase.views.FundraiseViewSet, basename="fundraise")

router.register(r"grant", purchase.views.GrantViewSet, basename="grant")

router.register(r"feed", FeedViewSet, basename="feed")

router.register(r"funding_feed", FundingFeedViewSet, basename="funding_feed")

router.register(r"grant_feed", GrantFeedViewSet, basename="grant_feed")

router.register(r"journal_feed", JournalFeedViewSet, basename="journal_feed")

# V2 API
router_v2 = routers.DefaultRouter()

router_v2.register(r"feed", FeedV2ViewSet, basename="feed_v2")

urlpatterns = [
    # Health check
    path(
        r"health/"
        + (settings.HEALTH_CHECK_TOKEN + "/" if settings.HEALTH_CHECK_TOKEN else ""),
        include("health_check.urls"),
    ),
    re_path(r"^api/", include(router.urls)),
    # v2 endpoints
    re_path(r"^api/v2/", include(router_v2.urls)),
    # TODO: calvinhlee - consolidate all mod views into 1 set
    path("api/get_hub_active_contributors/", editor_views.get_hub_active_contributors),
    path(
        "api/moderators/get_editors_by_contributions/",
        editor_views.get_editors_by_contributions,
    ),
    path(
        "api/rsc/get_rsc_circulating_supply",
        reputation.views.get_rsc_circulating_supply,
    ),
    path("api/permissions/", researchhub.views.permissions, name="permissions"),
    path("api/search/", include(search.urls)),
    # Referral endpoints
    path("api/referral/", include("referral.urls")),
    # Organization endpoints
    path(
        "api/organizations/non-profit/search/",
        NonprofitOrgViewSet.as_view({"get": "search"}),
        name="nonprofit-orgs-search",
    ),
    path(
        "api/organizations/non-profit/create/",
        NonprofitFundraiseLinkViewSet.as_view({"post": "create_nonprofit"}),
        name="nonprofit-create",
    ),
    path(
        "api/organizations/non-profit/link_to_fundraise/",
        NonprofitFundraiseLinkViewSet.as_view({"post": "link_to_fundraise"}),
        name="nonprofit-link-to-fundraise",
    ),
    path(
        "api/organizations/non-profit/get_by_fundraise/",
        NonprofitFundraiseLinkViewSet.as_view({"get": "get_by_fundraise"}),
        name="nonprofit-get-by-fundraise",
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
    path(
        "api/auth/register/verify-email/",
        CustomVerifyEmailView.as_view(),
        name="rest_verify_email",
    ),
    re_path(r"api/auth/register/", include("dj_rest_auth.registration.urls")),
    re_path(
        r"api/auth/login/", oauth.views.EmailLoginView.as_view(), name="rest_login"
    ),
    re_path(r"api/auth/logout/", LogoutView.as_view(), name="rest_logout"),
    re_path(
        r"api/auth/password-reset/$", PasswordResetView.as_view(), name="password-reset"
    ),
    re_path(
        r"api/auth/confirm/$",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    re_path(
        r"api/auth/password-change/$",
        PasswordChangeView.as_view(),
        name="password-change",
    ),
    re_path(
        r"^password-reset/confirm/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,32})/$",
        PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    re_path(r"^auth/signup/", include(oauth.urls.registration_urls)),
    re_path(r"^auth/", include(oauth.urls.default_urls)),
    path(
        "api/ckeditor/webhook/document_removed/",
        note_views.note_view.ckeditor_webhook_document_removed,
    ),
    path("api/ckeditor/token/", note_views.note_view.ckeditor_token),
    path("email_notifications/", mailing_list.views.email_notifications),
    path("", researchhub.views.index, name="index"),
    path(
        "api/asset/upload/",
        asset_upload_view.AssetUploadView.as_view(),
        name="asset_upload",
    ),
    path(
        "paper/upload/",
        paper_upload_views.PaperUploadView.as_view(),
        name="paper_upload",
    ),
    path("robots.txt", researchhub.views.robots_txt, name="robots_txt"),
    path(
        "webhooks/persona/",
        persona_webhook_view.PersonaWebhookView.as_view(),
        name="persona_webhook",
    ),
    path(
        "webhooks/sift/",
        sift_webhook_view.SiftWebhookView.as_view(),
        name="sift_webhook",
    ),
    path(
        "webhooks/stripe/",
        stripe_webhook_view.StripeWebhookView.as_view(),
        name="stripe_webhook",
    ),
    path(
        "api/payment/checkout-session/",
        purchase.views.CheckoutView.as_view(),
        name="payment_view",
    ),
    path(
        "api/payment/payment-intent/",
        purchase.views.PaymentIntentView.as_view(),
        name="payment_intent_view",
    ),
    path("user_saved/", UserSavedView.as_view(), name="user_saved"),
]

if "silk" in settings.INSTALLED_APPS:
    urlpatterns = [
        path("silk/", include("silk.urls", namespace="silk")),
    ] + urlpatterns

if settings.USE_DEBUG_TOOLBAR:
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]

"""researchhub URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework import routers

import discussion.views
import ethereum.urls
import hub.views
import mailing_list.views
import oauth.urls
import oauth.views
import paper.views
import reputation.views
import researchhub.views
import search.urls
import summary.views
import user.views

from researchhub.settings import CLOUD

router = routers.DefaultRouter()

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
    r'university',
    user.views.UniversityViewSet,
    basename='university'
)

router.register(
    r'email_recipient',
    mailing_list.views.EmailRecipientViewSet,
    basename='email_recipient'
)

router.register(r'user', user.views.UserViewSet)

router.register(r'withdrawal', reputation.views.WithdrawalViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('email_notifications/', mailing_list.views.email_notifications),
    path('health/', researchhub.views.healthcheck),

    re_path(r'^api/', include(router.urls)),
    path('api/ethereum/', include(ethereum.urls)),
    path(
        'api/permissions/',
        researchhub.views.permissions,
        name='permissions'
    ),
    path('api/search/', include(search.urls)),
    path(
        'api/auth/google/login/',
        oauth.views.GoogleLogin.as_view(),
        name='google_login'
    ),
    path(
        'api/auth/orcid/login/',
        oauth.views.OrcidLogin.as_view(),
        name='orcid_login'
    ),
    path(r'api/auth/', include('rest_auth.urls')),
    path(
        'auth/google/login/callback/',
        oauth.views.google_callback,
        name='google_callback'
    ),
    path(
        'auth/orcid/login/callback/',
        oauth.views.orcid_callback,
        name='orcid_callback'
    ),
    re_path(r'^auth/signup/', include(oauth.urls.registration_urls)),
    re_path(r'^auth/', include(oauth.urls.default_urls)),

    path(r'api/auth/', include('rest_auth.urls')),
    path('', researchhub.views.index, name='index'),
]

if not CLOUD:
    urlpatterns += [path('silk/', include('silk.urls', namespace='silk'))]

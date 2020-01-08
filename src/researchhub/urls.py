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
from researchhub import views as index_views
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
    path('test/', mailing_list.views.test),
    path('email_notifications/', mailing_list.views.email_notifications),
    path('health/', index_views.healthcheck),

    re_path(r'^api/', include(router.urls)),
    path('api/ethereum/', include(ethereum.urls)),
    path('api/permissions/', index_views.permissions, name='permissions'),
    path('api/search/', include(search.urls)),
    path(
        'auth/google/login/callback/',
        oauth.views.google_callback,
        name='google_callback'
    ),
    path(
        'api/auth/google/login/',
        oauth.views.GoogleLogin.as_view(),
        name='google_login'
    ),
    re_path(r'^auth/signup/', include(oauth.urls.registration_urls)),
    re_path(r'^auth/', include(oauth.urls.default_urls)),

    path(r'api/auth/', include('rest_auth.urls')),
    path('', index_views.index, name='index'),
]

if not CLOUD:
    urlpatterns += [path('silk/', include('silk.urls', namespace='silk'))]

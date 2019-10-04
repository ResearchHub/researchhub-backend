"""researchhub URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework import routers
from django.views.decorators.csrf import csrf_exempt

from .views import index
import discussion.views
import paper.views
import oauth.urls
import oauth.views
import user.views
import summary.views
import hub.views

router = routers.DefaultRouter()

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

router.register(r'user', user.views.UserViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    re_path(r'^api/', include(router.urls)),
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
    path('', index, name='index'),
]

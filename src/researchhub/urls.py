"""researchhub URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework import routers

from .views import index
import paper.views
import oauth.urls
import oauth.views
import user.views


router = routers.DefaultRouter()

router.register(r'user', user.views.UserViewSet)
router.register(r'paper', paper.views.PaperViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    re_path(r'^api/', include(router.urls)),
    re_path(
        r'^auth/google/login/callback/',
        oauth.views.google_callback,
        name='google_callback'
    ),
    re_path(
        r'^auth/google/login/',
        oauth.views.google_login,
        name='google_login'
    ),
    re_path(r'^auth/signup/', include(oauth.urls.registration_urls)),
    re_path(r'^auth/', include(oauth.urls.default_urls)),
    path('', index, name='index'),
]

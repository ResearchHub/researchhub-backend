"""researchhub URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.2/topics/http/urls/
"""
from django.conf.urls import url, include
from django.contrib import admin
from django.urls import path
from rest_framework import routers

from .views import index
import oauth.urls
import oauth.views
import user.views


router = routers.DefaultRouter()

router.register(r'user', user.views.UserViewSet)

urlpatterns = [
    path('admin/', admin.site.urls),
    url(r'^api/', include(router.urls)),
    url(r'^auth/google/login/callback/', oauth.views.google_callback, name='google_callback'),
    url(r'^auth/google/login/', oauth.views.google_login, name='google_login'),
    url(r'^auth/login/', oauth.views.token_login),
    url(r'^auth/', include(oauth.urls.default_urls)),
    path('', index, name='index'),
]

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Paper, Vote

admin.site.register(Vote)
admin.site.register(Paper)

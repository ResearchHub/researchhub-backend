from django.contrib import admin

from researchhub.admin import IdFilter, UploadedDateFilter
from .models import Paper, Vote


class PaperAdmin(admin.ModelAdmin):
    list_filter = (IdFilter, UploadedDateFilter)


admin.site.register(Vote)
admin.site.register(Paper, PaperAdmin)

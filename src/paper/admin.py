from django.contrib import admin

from researchhub.admin import IdFilter, UploadedDateFilter, TimeoutPaginator

from .models import Paper, Vote


class PaperAdmin(admin.ModelAdmin):
    list_filter = (IdFilter, UploadedDateFilter)
    paginator = TimeoutPaginator


admin.site.register(Vote)
admin.site.register(Paper, PaperAdmin)

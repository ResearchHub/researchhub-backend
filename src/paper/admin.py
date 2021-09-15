from django.contrib import admin

from researchhub.admin import IdFilter, UploadedDateFilter, TimeoutPaginator

from .models import Paper, Vote, Flag


class PaperAdmin(admin.ModelAdmin):
    list_filter = (IdFilter, UploadedDateFilter)
    paginator = TimeoutPaginator
    exclude = ['summary', 'moderators']
    raw_id_fields = ['authors', 'references']


admin.site.register(Vote)
admin.site.register(Flag)
admin.site.register(Paper, PaperAdmin)

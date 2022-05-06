from django.contrib import admin

from researchhub.admin import IdFilter, TimeoutPaginator, UploadedDateFilter

from .models import FlagPaperLegacy, Paper, VotePaperLegacy


class PaperAdmin(admin.ModelAdmin):
    list_filter = (IdFilter, UploadedDateFilter)
    paginator = TimeoutPaginator
    exclude = ["summary", "moderators"]
    raw_id_fields = ["authors", "references"]


admin.site.register(VotePaperLegacy)
admin.site.register(FlagPaperLegacy)
admin.site.register(Paper, PaperAdmin)

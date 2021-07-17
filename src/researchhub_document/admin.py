from django.contrib import admin

from researchhub.admin import IdFilter, TimeoutPaginator
from .models import ResearchhubPost, ResearchhubUnifiedDocument


class PostAdmin(admin.ModelAdmin):
    paginator = TimeoutPaginator
    list_filter = (IdFilter,)
    raw_id_fields = ['unified_document']


class UnifiedDocumentAdmin(admin.ModelAdmin):
    paginator = TimeoutPaginator
    list_filter = (IdFilter,)
    raw_id_fields = ['paper']


admin.site.register(ResearchhubPost, PostAdmin)
admin.site.register(ResearchhubUnifiedDocument, UnifiedDocumentAdmin)

from django.contrib import admin

from researchhub.admin import IdFilter
from .models import ResearchhubPost, ResearchhubUnifiedDocument


class PostAdmin(admin.ModelAdmin):
    list_filter = (IdFilter,)


admin.site.register(ResearchhubPost, PostAdmin)
admin.site.register(ResearchhubUnifiedDocument, PostAdmin)

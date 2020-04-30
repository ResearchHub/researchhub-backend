from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Paper, Vote


class PaperAdmin(admin.ModelAdmin):
    search_fields = ('id', 'uploaded_date',)


admin.site.register(Vote)
admin.site.register(Paper, PaperAdmin)

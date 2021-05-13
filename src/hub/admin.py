from django.contrib import admin
from .models import Hub, HubCategory


class HubAdmin(admin.ModelAdmin):
    model = Hub
    filter_horizontal = ('subscribers',)  # If you don't specify this, you will get a multiple select widget.


class HubCategoryAdmin(admin.ModelAdmin):
    model = HubCategory


admin.site.register(Hub, HubAdmin)
admin.site.register(HubCategory, HubCategoryAdmin)

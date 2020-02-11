from django.contrib import admin
from .models import Hub


class HubAdmin(admin.ModelAdmin):
     model=Hub
     filter_horizontal = ('subscribers',) #If you don't specify this, you will get a multiple select widget.

admin.site.register(Hub, HubAdmin)

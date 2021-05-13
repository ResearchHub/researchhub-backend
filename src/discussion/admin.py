from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from researchhub.admin import UserIdFilter, CreatedDateFilter
from .models import Vote, Thread, Reply, Comment


class VoteAdmin(admin.ModelAdmin):
    list_filter = (UserIdFilter, CreatedDateFilter)


class DiscussionAdmin(admin.ModelAdmin):
    list_filter = (UserIdFilter, CreatedDateFilter)


admin.site.register(Vote, VoteAdmin)
admin.site.register(Thread, DiscussionAdmin)
admin.site.register(Reply, DiscussionAdmin)
admin.site.register(Comment, DiscussionAdmin)

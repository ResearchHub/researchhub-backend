from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Vote, Thread, Reply, Comment


class InputFilter(admin.SimpleListFilter):
    template = 'admin_panel_input_filter.html'

    def lookups(self, request, model_admin):
        # Dummy, required to show the filter.
        return ((),)

    def choices(self, changelist):
        # Grab only the "all" option.
        all_choice = next(super().choices(changelist))
        all_choice['query_parts'] = (
            (k, v)
            for k, v in changelist.get_filters_params().items()
            if k != self.parameter_name
        )
        yield all_choice


class UserIdFilter(InputFilter):
    parameter_name = 'UserID'
    title = ('User ID')

    def queryset(self, request, queryset):
        if self.value() is not None:
            uid = self.value()
            return queryset.filter(created_by_id=uid)
        return queryset


class CreatedDateFilter(InputFilter):
    parameter_name = 'CreatedDate'
    title = ('Created Date')

    def queryset(self, request, queryset):
        if self.value() is not None:
            date = self.value()
            return queryset.filter(created_date__icontains=date)
        return queryset


class VoteAdmin(admin.ModelAdmin):
    search_fields = ('created_by__id', 'created_date',)


class DiscussionAdmin(admin.ModelAdmin):
    list_filter = (UserIdFilter, CreatedDateFilter)
    search_fields = ('created_by__id', 'created_date',)


admin.site.register(Vote, VoteAdmin)
admin.site.register(Thread, DiscussionAdmin)
admin.site.register(Reply, DiscussionAdmin)
admin.site.register(Comment, DiscussionAdmin)

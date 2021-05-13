from django.contrib import admin


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


class IdFilter(InputFilter):
    parameter_name = 'ID'
    title = ('ID')

    def queryset(self, request, queryset):
        item_id = self.value()
        if item_id:
            return queryset.filter(id=item_id)
        return queryset


class UserIdFilter(InputFilter):
    parameter_name = 'UserID'
    title = ('User ID')

    def queryset(self, request, queryset):
        uid = self.value()
        if uid:
            return queryset.filter(created_by_id=uid)
        return queryset


class CreatedDateFilter(InputFilter):
    parameter_name = 'CreatedDate'
    title = ('Created Date')

    def queryset(self, request, queryset):
        date = self.value()
        if date:
            return queryset.filter(created_date__icontains=date)
        return queryset


class UploadedDateFilter(InputFilter):
    parameter_name = 'UploadedDate'
    title = ('Uploaded Date')

    def queryset(self, request, queryset):
        date = self.value()
        if date:
            return queryset.filter(uploaded_date__icontains=date)
        return queryset

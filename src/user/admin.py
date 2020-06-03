from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db import models
from django.shortcuts import render
from .models import User


class AnalyticModel(models.Model):

    class Meta:
        verbose_name_plural = 'Analytics'
        app_label = 'user'


class AnalyticForm(forms.ModelForm):
    extra_field = forms.CharField()

    def save(self, commit=True):
        extra_field = self.cleaned_data.get('extra_field', None)
        # ...do something with extra_field here...
        return super(AnalyticForm, self).save(commit=commit)

    class Meta:
        fields = '__all__'
        model = AnalyticModel


class DummyModelAdmin(admin.ModelAdmin):
    model = AnalyticModel
    form = AnalyticForm

    # fieldsets = (
    #     (None, {
    #         'fields': ('name', 'description', 'extra_field',),
    #     }),
    # )

    def changelist_view(self, request):
        # cl = self.get_changelist_instance(request)
        context = {
            'title': 'Website Analytics'
        }
        return render(request, 'monthly_contributors.html', context)
    # change_form_template = 'monthly_contributors.html'
    # change_list_template = 'monthly_contributors.html'

    # def my_custom_view(self, request):
    #     # import pdb; pdb.set_trace()
    #     context = dict(
    #         self.admin_site.each_context(request),
    #     )
    #     template = TemplateResponse(request, 'monthly_contributors.html', context)
    #     # import pdb; pdb.set_trace()
    #     return template

    # def get_urls(self):
    #     urls = super().get_urls()
    #     my_urls = [
    #         path('monthly_contributors/', self.my_custom_view),
    #     ]
    #     return my_urls + urls

    # def get_urls(self):
    #     view_name = '{}_{}_changelist'.format(
    #         self.model._meta.app_label, self.model._meta.model_name)
    #     return [
    #         path('monthly_contributors/', self.my_custom_view, name=view_name),
    #     ]

    # def change_view(self, request, object_id, form_url='', extra_context=None):
    #     extra_context = extra_context or {}
    #     extra_context['osm_data'] = self.get_osm_info()
    #     return super().change_view(
    #         request, object_id, form_url, extra_context=extra_context,
    #     )


admin.site.register(AnalyticModel, DummyModelAdmin)
admin.site.register(User, UserAdmin)

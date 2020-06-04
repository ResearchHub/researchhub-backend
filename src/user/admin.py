import pandas as pd
import json
import datetime

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db import models
from django.http import JsonResponse, HttpRequest
from django.shortcuts import render
from django.urls import path

from .models import User, Action


class AnalyticModel(models.Model):

    class Meta:
        verbose_name_plural = 'Analytics'
        app_label = 'user'


class AnalyticAdminPanel(admin.ModelAdmin):
    model = AnalyticModel

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'chart_data/',
                self.admin_site.admin_view(self.chart_data_viewset)
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request):
        context = {
            'title': 'Website Analytics',
            'chart_data': json.loads(
                self.chart_data_viewset(HttpRequest()).getvalue()
            )
        }
        return render(request, 'monthly_contributors.html', context)

    def chart_data_viewset(self, request):
        start_date = request.GET.get('start_date', '2020-01-01')
        end_date = request.GET.get('end_date', datetime.datetime.now())
        actions = Action.objects.filter(
            created_date__gte=start_date,
            created_date__lte=end_date,
            user__isnull=False,
        ).order_by(
            '-created_date'
        ).annotate(
            date=models.functions.TruncDate('created_date')
        )
        actions_created_dates = actions.values_list(
            'date',
            flat=True
        )
        actions_user_ids = actions.values_list(
            'user',
            flat=True
        )

        actions_df = pd.DataFrame(data={
            'created_date': actions_created_dates,
            'user_id': actions_user_ids,
            }
        )
        actions_df['created_date'] = actions_df['created_date'].apply(
            lambda date: date.strftime('%Y-%m')
        )
        unique_contributors_by_date = actions_df.groupby('created_date').apply(
            lambda row: len(row['user_id'].unique())
        )
        data = []
        for date, count in zip(
            unique_contributors_by_date.index,
            unique_contributors_by_date.values
        ):
            data.append({'date': date, 'y': int(count)})

        res = JsonResponse(data, safe=False)
        return res


admin.site.register(AnalyticModel, AnalyticAdminPanel)
admin.site.register(User, UserAdmin)

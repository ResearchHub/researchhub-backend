import pandas as pd
import json
import datetime
from dateutil.rrule import rrule, MONTHLY

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
        data = json.loads(self.chart_data_viewset(HttpRequest()).getvalue())
        context = {
            'title': 'Website Analytics',
            'chart_data': data['chart_data'],
        }
        return render(request, 'monthly_contributors.html', context)

    def get_actions_dataframe(self, start_date, end_date):
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
            'created_date': pd.to_datetime(actions_created_dates),
            'user_id': actions_user_ids,
            }
        )
        return actions_df

    def get_unique_users(self, group):
        users = group['user_id'].unique().tolist()
        user_emails = User.objects.filter(
            id__in=users
        ).values_list(
            'email', flat=True
        )
        return {'count': len(users), 'users': list(user_emails)}

    def process_data(self, start_date, end_date, days_range, chart_selector):
        if chart_selector == 'day':
            res_date_format = '%Y-%m-%d'
            actions_df = self.get_actions_dataframe(start_date, end_date)
            days_offset = 30 - actions_df.created_date.max().day

            normalized_dates = (
                actions_df['created_date'] + pd.DateOffset(days=days_offset)
            )
            actions_df['normalized_date'] = normalized_dates

            unique_con_df = actions_df.groupby(
                pd.Grouper(
                    key='normalized_date',
                    freq=f'{days_range}MS',
                    closed='left',
                    label='right'
                )
            ).apply(
                self.get_unique_users
            ).to_frame().reset_index()

            original_created_date = (
                unique_con_df['normalized_date'] -
                pd.DateOffset(months=1) +
                pd.DateOffset(days=30 - days_offset - 1)
            )
            unique_con_df['created_date'] = original_created_date

            unique_contributors_df = unique_con_df[
                ['created_date', 0]
            ].set_index(
                'created_date'
            )

        elif chart_selector == 'month':
            res_date_format = '%Y-%m'
            actions_df = self.get_actions_dataframe(start_date, end_date)
            unique_con_df = actions_df.groupby(
                pd.Grouper(
                    key='created_date',
                    freq='M'
                )
            ).apply(
                self.get_unique_users
            ).to_frame().reset_index()

            unique_contributors_df = unique_con_df[
                ['created_date', 0]
            ].set_index(
                'created_date'
            )
        else:
            unique_contributors_df = pd.DataFrame()

        chart_data = []
        for date, user_data in zip(
            unique_contributors_df.index,
            unique_contributors_df.values
        ):
            user_data = user_data[0]
            count = user_data['count']
            unique_users = user_data['users']
            chart_data.append({
                'date': date.strftime(res_date_format),
                'y': count,
                'users': unique_users
            })

        data = {'chart_data': chart_data}
        return JsonResponse(data, safe=False)

    def chart_data_viewset(self, request):
        start_date = request.GET.get(
            'start_date',
            '2020-01-01'
        )
        end_date = request.GET.get(
            'end_date',
            datetime.datetime.now().strftime('%Y-%m-%dT%H:%M')
        )
        days_range = request.GET.get(
            'days_range',
            '1'
        )
        chart_selector = request.GET.get(
            'chart_selector',
            'day'
        )
        start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d')
        end_date = datetime.datetime.strptime(end_date, '%Y-%m-%dT%H:%M')

        res = self.process_data(
            start_date,
            end_date,
            days_range,
            chart_selector
        )

        # created_dates = [
        #     dt.strftime('%Y-%m-%d') for dt in rrule(
        #         MONTHLY, dtstart=start_date,
        #         until=end_date
        #     )
        # ]

        return res


admin.site.register(AnalyticModel, AnalyticAdminPanel)
admin.site.register(User, UserAdmin)

import pandas as pd
import json
import datetime
from time import time

from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.contrib.auth.admin import UserAdmin
from django.db import models
from django.http import JsonResponse, HttpRequest
from django.shortcuts import render, redirect
from django.urls import path

from .models import User, Action, Verification
from reputation.distributor import Distributor
from reputation import distributions
from mailing_list.lib import base_email_context
from utils.message import send_email_message
from researchhub.settings import BASE_FRONTEND_URL


class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
            ('Labels', {'fields': ('probable_spammer', 'is_suspended', 'moderator')}),
    )

    def save_model(self, request, obj, form, change):
        user = request.user
        changed_spam_status = 'probable_spammer' in form.changed_data
        changed_suspended_status = 'is_suspended' in form.changed_data
        if changed_spam_status or changed_suspended_status:
            user.set_probable_spammer(obj.probable_spammer)
            user.set_suspended(obj.is_suspended)
        super().save_model(request, obj, form, change)


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
            id__in=users,
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


class VerificationFilter(SimpleListFilter):
    title = 'Academic Verification'
    parameter_name = 'user__author_profile__academic_verification'

    def lookups(self, request, model_admin):
        return (
            (True, 'Approved'),
            (False, 'Rejected'),
            ('unknown', 'Awaiting Verification')
        )

    def queryset(self, request, qs):
        value = self.value()

        if not value:
            return qs

        if value == 'unknown':
            value = None

        return qs.filter(user__author_profile__academic_verification=value)


class VerificationAdminPanel(admin.ModelAdmin):
    model = Verification
    change_form_template = 'verification_change_form.html'
    list_filter = (VerificationFilter,)
    exclude = ('user', 'file')
    # fieldsets = (
    #     (None, {
    #         'fields': ('user',)
    #     }),
    # )

    def get_queryset(self, request):
        unique = Verification.objects.order_by(
            'user_id',
            'id'
        ).distinct(
            'user_id',
        ).values_list(
            'id'
        )
        qs = super(VerificationAdminPanel, self).get_queryset(request)
        qs = qs.filter(id__in=unique)
        return qs

    def change_view(self, request, object_id, form_url='', extra_context=None):
        images = ''
        obj = self.model.objects.get(id=object_id)
        user = obj.user
        referrer = user.invited_by
        verifications = self.model.objects.filter(user=user)

        for i, verification in enumerate(verifications.iterator()):
            if verification.file:
                url = verification.file.url
                image_html = f"""
                    <div style="display:inline-grid;padding:10px">
                        <span>
                            <a href="{url}" target="_blank">
                                <img src="{url}" style="max-width:300px;">
                            </a>
                        </span>
                        <label for="id_file">Image {i + 1}</label>
                    </div>
                """
                images += image_html

        is_verified = user.author_profile.academic_verification
        if is_verified:
            verified = """<img src="/static/admin/img/icon-yes.svg">"""
        elif is_verified is False:
            verified = """<img src="/static/admin/img/icon-no.svg">"""
        else:
            verified = """<img src="/static/admin/img/icon-unknown.svg">"""

        user_html = f"""
            <p style="font-weight:bold;">
                {user.id}: {user.email} / {user.first_name} {user.last_name}
            </p>
        """

        if referrer:
            referred_by = f"""
                <p style="font-weight:bold;">
                    {referrer.id}: {referrer.email} / {referrer.first_name} {referrer.last_name}
                </p>
            """
        else:
            referred_by = """<p> No Referrer </p>"""

        extra_context = extra_context or {}
        extra_context['images'] = images
        extra_context['verified'] = verified
        extra_context['user'] = user_html
        extra_context['referred_by'] = referred_by

        return super(VerificationAdminPanel, self).change_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def response_change(self, request, obj):
        user = obj.user
        if '_approve' in request.POST:
            author_profile = user.author_profile
            author_profile.academic_verification = True
            author_profile.save()
            user_distribution_record = self.distribute_referral_reward(user)
            self.send_academic_verification_email(user, user_distribution_record)
            return redirect('.')
        elif '_reject' in request.POST:
            author_profile = user.author_profile
            author_profile.academic_verification = False
            author_profile.save()
            return redirect('.')
        return super().response_change(request, obj)

    def send_academic_verification_email(self, user, user_distribution_record):
        author_profile = user.author_profile
        user_name = author_profile.first_name
        if author_profile.last_name:
            user_name += ' ' + author_profile.last_name

        context = {
            **base_email_context,
            'user_name': user_name,
            'reward_amount': user_distribution_record.amount,
            'user_profile': f'{BASE_FRONTEND_URL}/user/{user.id}/overview',
        }

        subject = 'Your ResearchHub Verification is Approved!'
        send_email_message(
            user.email,
            'academic_verification_email.txt',
            subject,
            context,
            html_template='academic_verification_email.html'
        )

    def distribute_referral_reward(self, user):
        timestamp = time()

        referrer = user.invited_by
        if not referrer:
            referrer = user

        distribution = Distributor(
            distributions.ReferralApproved,
            user,
            referrer,
            timestamp,
            None,
        )
        referred_distribution_record = distribution.distribute()

        if referrer:
            distribution = Distributor(
                distributions.ReferralApproved,
                referrer,
                referrer,
                timestamp,
                None,
            )
            distribution.distribute()

        return referred_distribution_record


admin.site.register(AnalyticModel, AnalyticAdminPanel)
admin.site.register(User, CustomUserAdmin)
admin.site.register(Verification, VerificationAdminPanel)

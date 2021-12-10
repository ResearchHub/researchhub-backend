import time
from django.contrib import admin
from django.db import models

from reputation.models import Distribution
from reputation.distributor import Distributor
from reputation.distributions import Distribution as Dist
from user.models import User


class RewardModel(models.Model):

    class Meta:
        verbose_name_plural = 'Reward'
        app_label = 'reputation'


class RewardAdminModel(admin.ModelAdmin):
    model = Distribution
    add_form_template = 'rsc_reward.html'

    def get_queryset(self, request):
        return Distribution.objects.all() 

    def render_change_form(self, request, context, *args, **kwargs):
        context.update(
            {
                'title': 'Grant RSC',
                'show_save_and_add_another': False,
                'show_save_and_continue': False,
                'has_delete_permission': False,
                'has_change_permission': False,
            }
        )
        return super().render_change_form(request, context, *args, **kwargs)

    def save_model(self, request, *args, **kwargs):
        data = request._post
        user_id = data.get('user_id')
        amount = int(data.get('amount', 0))
        give_rep = data.get('give_rep', 'off') == 'on'

        user = User.objects.get(id=user_id)
        distribution = Dist('REWARD', amount, give_rep=give_rep)
        distributor = Distributor(
                    distribution,
                    user,
                    user,
                    time.time()
                )
        distributor.distribute()

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


def make_published(modeladmin, request, queryset):
    queryset.update(status='p')


class DistributionAdmin(admin.ModelAdmin):
    actions = [make_published]


# admin.site.register(RewardModel, RewardAdminModel)
admin.site.register(Distribution, DistributionAdmin)

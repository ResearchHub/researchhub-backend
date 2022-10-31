import time

from django.contrib import admin
from django.db import models

from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Distribution
from user.models import User


class RewardModel(models.Model):
    class Meta:
        verbose_name_plural = "Reward"
        app_label = "reputation"


class RewardAdminModel(admin.ModelAdmin):
    model = Distribution
    add_form_template = "rsc_reward.html"
    change_form_template = "rsc_reward.html"

    def get_queryset(self, request):
        return Distribution.objects.all()

    # def render_change_form(self, request, context, *args, **kwargs):
    #     context.update(
    #         {
    #             'title': 'Grant RSC',
    #             'show_save_and_add_another': False,
    #             'show_save_and_continue': False,
    #             'has_delete_permission': False,
    #             'has_change_permission': False,
    #         }
    #     )
    #     return super().render_change_form(request, context, *args, **kwargs)

    # def save_model(self, request, *args, **kwargs):
    #     data = request._post
    #     user_id = data.get('user_id')
    #     amount = int(data.get('amount', 0))
    #     give_rep = data.get('give_rep', 'off') == 'on'

    #     user = User.objects.get(id=user_id)
    #     distribution = Dist('REWARD', amount, give_rep=give_rep)
    #     distributor = Distributor(
    #                 distribution,
    #                 user,
    #                 user,
    #                 time.time()
    #             )
    #     distributor.distribute()

    def render_change_form(self, request, context, *args, **kwargs):
        print(context)
        # context.update(
        #     {
        #         'title': 'Grant RSC',
        #         'show_save_and_add_another': False,
        #         'show_save_and_continue': False,
        #         'has_delete_permission': False,
        #         'has_change_permission': False,
        #     }
        # )
        return super().render_change_form(request, context, *args, **kwargs)

    def add_view(self, request, form_url="", extra_context=None):
        user_html = """
            <input type="number" id="user_id" name="_grant_OLD"/>
        """
        # images = ''
        # obj = self.model.objects.get(id=object_id)
        # user = obj.user
        # referrer = user.invited_by
        # verifications = self.model.objects.filter(user=user)

        # for i, verification in enumerate(verifications.iterator()):
        #     if verification.file:
        #         url = verification.file.url
        #         image_html = f"""
        #             <div style="display:inline-grid;padding:10px">
        #                 <span>
        #                     <a href="{url}" target="_blank">
        #                         <img src="{url}" style="max-width:300px;">
        #                     </a>
        #                 </span>
        #                 <label for="id_file">Image {i + 1}</label>
        #             </div>
        #         """
        #         images += image_html

        # is_verified = user.author_profile.academic_verification
        # if is_verified:
        #     verified = """<img src="/static/admin/img/icon-yes.svg">"""
        # elif is_verified is False:
        #     verified = """<img src="/static/admin/img/icon-no.svg">"""
        # else:
        #     verified = """<img src="/static/admin/img/icon-unknown.svg">"""

        # user_html = f"""
        #     <p style="font-weight:bold;">
        #         {user.id}: {user.email} / {user.first_name} {user.last_name}
        #     </p>
        # """

        # if referrer:
        #     referred_by = f"""
        #         <p style="font-weight:bold;">
        #             {referrer.id}: {referrer.email} / {referrer.first_name} {referrer.last_name}
        #         </p>
        #     """
        # else:
        #     referred_by = """<p> No Referrer </p>"""

        extra_context = extra_context or {}
        # extra_context['images'] = images
        # extra_context['verified'] = verified
        extra_context["user"] = user_html
        # extra_context['referred_by'] = referred_by

        return super(RewardAdminModel, self).add_view(
            request,
            form_url,
            extra_context=extra_context,
        )

    def response_change(self, request, obj):
        print("on change---------------")
        # user = obj.user
        if "_grant_OLD" in request.POST:
            author_profile = user.author_profile
            author_profile.academic_verification = True
            author_profile.save()
            self.send_academic_verification_email(user, user_distribution_record)
            return redirect(".")
        elif "_reject" in request.POST:
            author_profile = user.author_profile
            author_profile.academic_verification = False
            author_profile.save()
            return redirect(".")
        return super().response_change(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


def make_published(modeladmin, request, queryset):
    queryset.update(status="p")


class DistributionAdmin(admin.ModelAdmin):
    actions = [make_published]


admin.site.register(RewardModel, RewardAdminModel)
# admin.site.register(Distribution, DistributionAdmin)

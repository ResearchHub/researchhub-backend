from allauth.account import app_settings as account_settings
from allauth.account.utils import complete_signup, user_username
from allauth.socialaccount.helpers import (
    AuthProcess,
    ImmediateHttpResponse,
    SocialLogin,
    _login_social_account,
    get_account_adapter,
    get_adapter,
    messages,
    reverse,
    signals,
)
from django.conf import settings
from django.forms import ValidationError
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from rest_framework.authtoken.models import Token

oauth_method = settings.OAUTH_METHOD


class OAuthMethods:
    TOKEN = "token"


"""
Copied from allauth/socialaccount/helpers.py
"""


def complete_social_login(request, sociallogin):
    assert not sociallogin.is_existing
    sociallogin.lookup()
    try:
        get_adapter(request).pre_social_login(request, sociallogin)
        signals.pre_social_login.send(
            sender=SocialLogin, request=request, sociallogin=sociallogin
        )
        process = sociallogin.state.get("process")
        if process == AuthProcess.REDIRECT:
            return _social_login_redirect(request, sociallogin)
        elif process == AuthProcess.CONNECT:
            return _add_social_account(request, sociallogin)
        else:
            return _complete_social_login(request, sociallogin)
    except ImmediateHttpResponse as e:
        return e.response


def _social_login_redirect(request, sociallogin):
    next_url = sociallogin.get_redirect_url(request) or "/"
    return _send_response(request, HttpResponseRedirect(next_url))


def _add_social_account(request, sociallogin):
    if request.user.is_anonymous:
        # This should not happen. Simply redirect to the connections
        # view (which has a login required)
        return HttpResponseRedirect(reverse("socialaccount_connections"))
    level = messages.INFO
    message = "socialaccount/messages/account_connected.txt"
    action = None
    if sociallogin.is_existing:
        if sociallogin.user != request.user:
            # Social account of other user. For now, this scenario
            # is not supported. Issue is that one cannot simply
            # remove the social account from the other user, as
            # that may render the account unusable.
            level = messages.ERROR
            message = "socialaccount/messages/account_connected_other.txt"
        else:
            # This account is already connected -- we give the opportunity
            # for customized behaviour through use of a signal.
            action = "updated"
            message = "socialaccount/messages/account_connected_updated.txt"
            signals.social_account_updated.send(
                sender=SocialLogin, request=request, sociallogin=sociallogin
            )
    else:
        # New account, let's connect
        action = "added"
        sociallogin.connect(request, request.user)
        signals.social_account_added.send(
            sender=SocialLogin, request=request, sociallogin=sociallogin
        )
    default_next = get_adapter(request).get_connect_redirect_url(
        request, sociallogin.account
    )
    next_url = sociallogin.get_redirect_url(request) or default_next
    get_account_adapter(request).add_message(
        request,
        level,
        message,
        message_context={"sociallogin": sociallogin, "action": action},
    )
    return _send_response(request, HttpResponseRedirect(next_url))


def complete_social_signup(request, sociallogin):
    return complete_signup(
        request,
        sociallogin.user,
        settings.ACCOUNT_EMAIL_VERIFICATION,
        sociallogin.get_redirect_url(request),
        signal_kwargs={"sociallogin": sociallogin},
    )


def _process_signup(request, sociallogin):
    # Ok, auto signup it is, at least the e-mail address is ok.
    # We still need to check the username though...

    if account_settings.USER_MODEL_USERNAME_FIELD:
        username = user_username(sociallogin.user)
        try:
            get_account_adapter(request).clean_username(username)
        except ValidationError:
            # This username is no good ...
            user_username(sociallogin.user, "")
    # FIXME: This part contains a lot of duplication of logic
    # ("closed" rendering, create user, send email, in active
    # etc..)
    if not get_adapter(request).is_open_for_signup(request, sociallogin):
        return render(
            request, "account/signup_closed." + account_settings.TEMPLATE_EXTENSION
        )
    get_adapter(request).save_user(request, sociallogin, form=None)
    ret = complete_social_signup(request, sociallogin)
    return ret


def _complete_social_login(request, sociallogin):
    if request.user.is_authenticated:
        get_account_adapter(request).logout(request)
    if sociallogin.is_existing:
        # Login existing user
        ret = _login_social_account(request, sociallogin)
        signals.social_account_updated.send(
            sender=SocialLogin, request=request, sociallogin=sociallogin
        )
    else:
        # New social user
        ret = _process_signup(request, sociallogin)

    return _send_response(request, ret)


"""
Custom helper methods not copied from allauth
"""


def _send_response(original_request, default_response):
    if oauth_method == OAuthMethods.TOKEN:
        return _respond_with_token(original_request.user)
    return default_response


def _respond_with_token(user):
    token = get_or_create_user_token(user)
    response = JsonResponse({"key": token})
    return response


def get_or_create_user_token(user):
    try:
        token = Token.objects.get(user=user)
    except Exception as e:
        print(e)
        token = Token.objects.create(user=user)
    return token.key

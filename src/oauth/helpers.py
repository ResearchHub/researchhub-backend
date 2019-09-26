from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from allauth.socialaccount.helpers import (
    get_adapter,
    get_account_adapter,
    signals,
    SocialLogin,
    AuthProcess,
    reverse,
    messages,
    ImmediateHttpResponse,
    _process_signup,
    _login_social_account
)
from rest_framework.authtoken.models import Token


oauth_method = settings.OAUTH_METHOD


class OAuthMethods:
    TOKEN = 'token'


'''
Copied from allauth/socialaccount/helpers.py
'''


def complete_social_login(request, sociallogin):
    assert not sociallogin.is_existing
    sociallogin.lookup()
    try:
        get_adapter(request).pre_social_login(request, sociallogin)
        signals.pre_social_login.send(sender=SocialLogin,
                                      request=request,
                                      sociallogin=sociallogin)
        process = sociallogin.state.get('process')
        if process == AuthProcess.REDIRECT:
            return _social_login_redirect(request, sociallogin)
        elif process == AuthProcess.CONNECT:
            return _add_social_account(request, sociallogin)
        else:
            return _complete_social_login(request, sociallogin)
    except ImmediateHttpResponse as e:
        return e.response


def _social_login_redirect(request, sociallogin):
    next_url = sociallogin.get_redirect_url(request) or '/'
    return _send_response(request, HttpResponseRedirect(next_url))


def _add_social_account(request, sociallogin):
    if request.user.is_anonymous:
        # This should not happen. Simply redirect to the connections
        # view (which has a login required)
        return HttpResponseRedirect(reverse('socialaccount_connections'))
    level = messages.INFO
    message = 'socialaccount/messages/account_connected.txt'
    action = None
    if sociallogin.is_existing:
        if sociallogin.user != request.user:
            # Social account of other user. For now, this scenario
            # is not supported. Issue is that one cannot simply
            # remove the social account from the other user, as
            # that may render the account unusable.
            level = messages.ERROR
            message = 'socialaccount/messages/account_connected_other.txt'
        else:
            # This account is already connected -- we give the opportunity
            # for customized behaviour through use of a signal.
            action = 'updated'
            message = 'socialaccount/messages/account_connected_updated.txt'
            signals.social_account_updated.send(
                sender=SocialLogin,
                request=request,
                sociallogin=sociallogin)
    else:
        # New account, let's connect
        action = 'added'
        sociallogin.connect(request, request.user)
        signals.social_account_added.send(sender=SocialLogin,
                                          request=request,
                                          sociallogin=sociallogin)
    default_next = get_adapter(request).get_connect_redirect_url(
        request,
        sociallogin.account)
    next_url = sociallogin.get_redirect_url(request) or default_next
    get_account_adapter(request).add_message(
        request, level, message,
        message_context={
            'sociallogin': sociallogin,
            'action': action
        }
    )
    return _send_response(request, HttpResponseRedirect(next_url))


def _complete_social_login(request, sociallogin):
    if request.user.is_authenticated:
        get_account_adapter(request).logout(request)
    if sociallogin.is_existing:
        # Login existing user
        ret = _login_social_account(request, sociallogin)
        signals.social_account_updated.send(
            sender=SocialLogin,
            request=request,
            sociallogin=sociallogin)
    else:
        # New social user
        ret = _process_signup(request, sociallogin)

    return _send_response(request, ret)


'''
Custom helper methods not copied from allauth
'''


def _send_response(original_request, default_response):
    if oauth_method == OAuthMethods.TOKEN:
        return _respond_with_token(original_request.user)
    else:
        return default_response


def _respond_with_token(user):
    token = get_or_create_user_token(user)
    response = JsonResponse({'key': token})
    return response


def get_or_create_user_token(user):
    try:
        token = Token.objects.get(user_id=user.id)
    except Exception as e:
        print(e)
        token = Token.objects.create(user=user)
    return token.key

def get_user_from_request(ctx):
    request = ctx.get("request")
    if request and hasattr(request, "user"):
        return request.user
    return None


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip

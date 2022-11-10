SEARCH_FOR_AUTHORS = "SEARCH_FOR_AUTHORS"
AUTHOR_PROFILE_LOOKUP = "AUTHOR_PROFILE_LOOKUP"


def handler(event, context):
    import controller

    for key in event:
        func = getattr(controller, key.lower(), None)
        if func:
            data = event[key]
            if not isinstance(data, list):
                data = [data]
            return func(*data)
    return event

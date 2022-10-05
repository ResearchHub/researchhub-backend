import math
from datetime import datetime

import pytz


def time_since(time):
    now = datetime.now(pytz.UTC)
    seconds_diff = (now - time).total_seconds()

    minute_diff = round(math.floor(seconds_diff / 60))
    hour_diff = round(math.floor(minute_diff / 60))
    days_diff = round(math.floor(hour_diff / 24))
    months_diff = round(math.floor(days_diff / 30))
    if (minute_diff) < 60:
        if minute_diff == 1:
            return f"{minute_diff} minute ago"
        return f"{minute_diff} minutes ago"
    elif hour_diff < 24:
        if hour_diff == 1:
            return f"{hour_diff} hour ago"
        return f"{hour_diff} hours ago"
    elif days_diff < 30:
        if days_diff == 1:
            return f"{days_diff} day ago"
        return f"{days_diff} days ago"
    elif months_diff < 12:
        if months_diff == 1:
            return f"{months_diff} month ago"
        return f"{months_diff} months ago"
    else:
        years_diff = round(math.floor(months_diff / 12))
        if years_diff == 1:
            return f"{years_diff} year ago"
        return f"{years_diff} years ago"

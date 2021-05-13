from elasticapm.conf.constants import TRANSACTION
from elasticapm.processors import for_events


@for_events(TRANSACTION)
def filter_processor(client, event):
    event_url = event['context']['request']['url']['full']
    if ('ignore_apm' in event_url) or ('/health/' in event_url):
        return False
    return event

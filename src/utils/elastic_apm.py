from elasticapm.conf.constants import TRANSACTION
from elasticapm.processors import for_events
from utils.sentry import log_info


@for_events(TRANSACTION)
def paper_processor(client, event):
    if event['type'] == 'request':
        event_url = event['context']['request']['url']['full']
        log_info(event_url)
        if 'ignore_apm' in event_url:
            return False
    return event

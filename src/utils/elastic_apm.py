from elasticapm.conf.constants import TRANSACTION
from elasticapm.processors import for_events
from utils.sentry import log_info


@for_events(TRANSACTION)
def custom_processor(client, event):
    event_url = event['context']['request']['url']['full']
    log_info(event_url)
    print(event_url)
    if 'ignore_apm' in event_url:
        log_info('Blocking')
        print('Blocking')
        return False
    return event

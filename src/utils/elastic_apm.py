from elasticapm.conf.constants import TRANSACTION
from elasticapm.processors import for_events
from utils.sentry import log_info


@for_events(TRANSACTION)
def paper_processor(client, event):
    log_info(event)
    print(event)
    return False

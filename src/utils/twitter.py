import twitter
import time

from twitter.error import TwitterError
from researchhub.settings import (
    TWITTER_CONSUMER_KEY,
    TWITTER_CONSUMER_SECRET,
    TWITER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET,
    TWITTER_CONSUMER_KEY_ALT,
    TWITTER_CONSUMER_SECRET_ALT,
    TWITER_ACCESS_TOKEN_ALT,
    TWITTER_ACCESS_TOKEN_SECRET_ALT,
)

api = twitter.Api(
    consumer_key=TWITTER_CONSUMER_KEY,
    consumer_secret=TWITTER_CONSUMER_SECRET,
    access_token_key=TWITER_ACCESS_TOKEN,
    access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
)
api_alt = twitter.Api(
    consumer_key=TWITTER_CONSUMER_KEY_ALT,
    consumer_secret=TWITTER_CONSUMER_SECRET_ALT,
    access_token_key=TWITER_ACCESS_TOKEN_ALT,
    access_token_secret=TWITTER_ACCESS_TOKEN_SECRET_ALT,
)
RATE_LIMIT_CODE = 88


def get_twitter_results(query, twitter_api=api):
    # To filter out retweets: add -filter:retweets to filters
    try:
        results = twitter_api.GetSearch(
            term=query,
            count=100
        )
    except TwitterError as e:
        error_message = e.message[0]
        code = error_message['code']
        if code == RATE_LIMIT_CODE and twitter_api != api_alt:
            return get_twitter_results(query, twitter_api=api_alt)
        else:
            raise e
    return results


def get_twitter_url_results(url, filters=''):
    term = f'{url}'
    if filters:
        term += filters
    return get_twitter_results(term)


def get_twitter_doi_results(doi, filters=''):
    term = f'{doi}'
    if filters:
        term += filters
    return get_twitter_results(term)


def get_twitter_search_rate_limit():
    rate_limit = api.rate_limit.get_limit('/1.1/search/tweets.json')
    remaining = rate_limit.remaining
    epoch_time = rate_limit.reset
    seconds_to_reset = round(epoch_time - time.time())
    return remaining, seconds_to_reset

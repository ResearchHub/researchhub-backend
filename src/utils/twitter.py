import twitter
import time

from researchhub.settings import (
    TWITTER_CONSUMER_KEY,
    TWITTER_CONSUMER_SECRET,
    TWITER_ACCESS_TOKEN,
    TWITTER_ACCESS_TOKEN_SECRET,
)

api = twitter.Api(
    consumer_key=TWITTER_CONSUMER_KEY,
    consumer_secret=TWITTER_CONSUMER_SECRET,
    access_token_key=TWITER_ACCESS_TOKEN,
    access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
)


def get_twitter_results(query):
    results = api.GetSearch(
        term=query
    )
    return results


def get_twitter_url_results(url, filters=' -filter:retweets'):
    term = f'{url}'
    if filters:
        term += filters
    return get_twitter_results(term)


def get_twitter_doi_results(doi, filters=' -filter:retweets'):
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

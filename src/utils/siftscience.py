import json
import sift.client

from researchhub.settings import SIFT_ACCOUNT_ID, SIFT_REST_API_KEY
from utils import sentry

# https://sift.com/resources/guides/content-abuse

client = sift.Client(api_key=SIFT_REST_API_KEY, account_id=SIFT_ACCOUNT_ID)


def get_user_score(user_id):
    try:
        response = client.score(user_id)
        out = json.dumps(response.body)
        print(out)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e)


def label_bad_user(user_id, abuse_type, description=''):
    # TODO: Finish this by determing how we plan to use it
    try:
        response = client.label(user_id, {
            "$is_bad": True,
            # optional fields
            "$abuse_type": abuse_type,
            "$description": description,
            "$source": 'django',
            "$analyst": 'dev@quantfive.org'
        })
        print(response.body)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e)


def unlabel_user(user_id):
    # TODO: Finish this by determing how we plan to use it
    try:
        response = client.unlabel(user_id, abuse_type='content_abuse')
        print(response.body)
    except sift.client.ApiException as e:
        sentry.log_error(e)
        print(e)


class EventsApi:

    def track_create_account(self, user, session_id):
        properties = {
            # Required Fields
            "$user_id": user.id,

            # Supported Fields
            "$session_id": session_id,
            "$user_email": user.email,
            "$name": user.full_name,
            "$social_sign_on_type": "$google",

            # TODO: Can we get this from headers? If so, apply to others below
            # Send this information from a BROWSER client.
            # "$browser"      : {
            #     "$user_agent" : "",
            #     "$accept_language"  : "en-US",
            #     "$content_language" : "en-GB"
            # },
        }
        try:
            response = client.track("$create_account", properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e)

    def track_update_account(self, user):
        # https://sift.com/developers/docs/curl/events-api/reserved-events/update-account
        pass

    def track_login(self, user):
        # https://sift.com/developers/docs/python/events-api/reserved-events/login
        pass

    def track_create_content_comment(self, user, comment, is_thread=False):
        root_content_id = ''
        if comment.paper is not None:
            root_content_id = f'{type(comment.paper)}_{comment.paper.id}',

        comment_properties = {
            # Required fields
            "$user_id": user.id,
            # must be unique across all content types
            "$content_id": f'{type(comment)}_{comment.id}',

            # Recommended fields
            # "$session_id"             : "a234ksjfgn435sfg",
            "$status": "$active",
            # "$ip"                     : "255.255.255.0",

            # Required $comment object
            "$comment": {
                "$body": comment.plain_text,
                "$contact_email": user.email,
                "$root_content_id": root_content_id,
                # TODO: Do we want to use this?
                # "$images"             : [
                # {
                #     "$md5_hash"       : "0cc175b9c0f1b6a831c399e269772661",
                #     "$link"           : "https://www.domain.com/file.png",
                #     "$description"    : "An old picture"
                # }
                # ]
            }
        }

        if not is_thread:
            comment_properties['$parent_comment_id'] = (
                f'{type(comment.parent)}_{comment.parent.id}'
            )

        try:
            response = client.track("$create_content", comment_properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e)

    def track_update_content_comment():
        # https://sift.com/developers/docs/curl/events-api/reserved-events/update-content
        pass

    def track_create_content_paper(self, user, paper):
        post_properties = {
            # Required fields
            "$user_id": user.id,
            "$content_id": f'{type(paper)}_{paper.id}',

            # Recommended fields
            # "$session_id"           : "a234ksjfgn435sfg",
            "$status": "$active",
            # "$ip"                   : "255.255.255.0",

            # Required $post object
            "$post": {
                "$subject": paper.title,
                "$body": paper.paper_title,
                "$contact_email": user.email,
                "$contact_address": {
                    "$name": user.full_name,
                },
                "$categories": paper.hubs.all(),
                # TODO: Can/should we use the pdf for images here?
                # "$images"           : [
                # {
                #     "$md5_hash"     : "0cc175b9c0f1b6a831c399e269772661",
                #     "$link"         : "https://www.domain.com/file.png",
                #     "$description"  : "View from the window!"
                # }
                # ],
            },
        }

        try:
            response = client.track("$create_content", post_properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e)

    def track_update_content_paper(self, user, paper):
        # https://sift.com/developers/docs/curl/events-api/reserved-events/update-content
        post_properties = {
            # Required fields
            "$user_id": user.id,
            "$content_id": f'{type(paper)}_{paper.id}',

            # Recommended fields
            # "$session_id"           : "a234ksjfgn435sfg",
            "$status": "$active",
            # "$ip"                   : "255.255.255.0",

            # Required $post object
            "$post": {
                "$subject": paper.title,
                "$body": paper.paper_title,
                "$contact_email": user.email,
                "$contact_address": {
                    "$name": user.full_name,
                },
                "$categories": paper.hubs.all(),
                # TODO: Can/should we use the pdf for images here?
                # "$images"           : [
                # {
                #     "$md5_hash"     : "0cc175b9c0f1b6a831c399e269772661",
                #     "$link"         : "https://www.domain.com/file.png",
                #     "$description"  : "View from the window!"
                # }
                # ],
            },
        }

        try:
            response = client.track("$update_content", post_properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e)

    def track_flag_content(self, user, content_id, referer_id):
        # https://sift.com/developers/docs/curl/events-api/reserved-events/flag-content
        properties = {
            "$user_id": user.id,
            "$content_id": content_id,
            "$flagged_by": referer_id
        }

        try:
            response = client.track("$flag_content", properties)
            print(response.body)
        except sift.client.ApiException as e:
            sentry.log_error(e)
            print(e)

    def track_content_status(self):
        # https://sift.com/developers/docs/python/events-api/reserved-events/content-status
        # TODO: We might not need this?
        properties = {
            "$user_id": '',
            "$content_id": '',
            "$status": ''
        }


events_api = EventsApi()
